"""
Cyphward Transactional Email Service — Brevo (Sendinblue) Integration
Sends executive security assessments, perimeter alerts, and board briefings.
Dual-layer delivery: Brevo REST API v3 (primary) + SMTP Relay (failover).
"""
import os
import asyncio
import json
import logging
import smtplib
from html import escape
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, List, Optional
import httpx

from backend.app.core.config import (
    BREVO_API_KEY,
    BREVO_SMTP_SERVER,
    BREVO_SMTP_PORT,
    BREVO_SMTP_LOGIN,
    BREVO_SMTP_PASSWORD,
    EMAIL_SENDERS,
    DEFAULT_EMAIL_SENDER_KIND,
)

logger = logging.getLogger("cyphward.mailer")


def email_sender(kind: str) -> "tuple[str, str]":
    """Resolve the (display name, address) pair for an email kind.

    Unknown kinds fall back to the system sender so a typo can never
    block delivery; the misspelling is logged loudly instead.
    """
    sender = EMAIL_SENDERS.get(kind)
    if sender is None:
        logger.warning(
            f"Unknown email sender kind {kind!r}; falling back to "
            f"{DEFAULT_EMAIL_SENDER_KIND!r} <{EMAIL_SENDERS[DEFAULT_EMAIL_SENDER_KIND][1]}>."
        )
        sender = EMAIL_SENDERS[DEFAULT_EMAIL_SENDER_KIND]
    return sender


def generate_executive_report_html(
    org_name: str,
    domain: str,
    score: Optional[float] = None,
    grade: Optional[str] = None,
    posture_label: str = "",
    assets_count: int = 0,
    critical_count: int = 0,
    high_count: int = 0,
    medium_count: int = 0,
    low_count: int = 0,
    resolved_recent_count: int = 0,
    summary_text: Optional[str] = None,
    drivers: Optional[List[Dict[str, Any]]] = None,
    scope_label: Optional[str] = None,
    coverage_label: Optional[str] = None,
    domain_line: Optional[str] = None,
    nuclei_line: Optional[str] = None,
    generated_at: Optional[datetime] = None,
    report_ref: Optional[str] = None,
    integrity_lines: Optional[List[str]] = None,
) -> str:
    """
    Renders a clean, light-themed HTML security report email in plain English.

    A report issued from a snapshot passes the snapshot's own time, reference and integrity lines, so
    the same snapshot always renders the same page. Without them the page is stamped with the current time.
    Compatible with Gmail, Apple Mail, Outlook, and webmail clients.

    A graded score (grade plus scope_label) is described as valid only within the
    declared scope. Ungraded results keep the "does not establish complete coverage"
    wording. The SCOPE block lists the coverage, per-domain and Nuclei lines when given.
    """
    assessed = score is not None
    if assessed:
        score_color = "#DC2626" if score < 70 else ("#D97706" if score < 85 else "#059669")
        score_width = max(2, min(100, int(score)))
        score_text = str(score)
        score_label = f"{score}/100"
        score_suffix = "/100"
        grade_text = str(grade or "not assigned")
        grade_line = f"Grade {escape(str(grade))} · {escape(posture_label)}" if grade else escape(posture_label)
    else:
        score_color = "#64748B"
        score_width = 0
        score_text = "—"
        score_label = "not assessed"
        score_suffix = ""
        grade_text = "not assessed"
        grade_line = f"{escape(posture_label or 'Not assessed')} · Insufficient evidence for a score"
    stamp = generated_at or datetime.now(timezone.utc)
    report_ref = report_ref or stamp.strftime("%Y%m%d-%H%M")
    generated_at = stamp.strftime("%Y-%m-%d %H:%M")

    if not summary_text:
        if assessed and grade and scope_label:
            coverage_sentence = f"Coverage: {coverage_label}. " if coverage_label else ""
            summary_text = (
                f"The available evidence gives {org_name} a known-risk score of {score} out of 100 "
                f"(grade {grade}, {posture_label}), which applies within declared scope. "
                f"{coverage_sentence}"
                "This is not a statement about security beyond the declared checks. "
                f"There are {critical_count} critical, {high_count} high, {medium_count} medium and {low_count} low open findings. "
                "Review the findings and recommended actions in your dashboard."
            )
        elif assessed:
            summary_text = (
                f"The available evidence gives {org_name} a known-risk score of {score} out of 100 "
                f"({posture_label}). This reflects recorded findings and does not establish complete coverage. "
                f"There are {critical_count} critical, {high_count} high, {medium_count} medium and {low_count} low open findings. "
                f"Review the findings and recommended actions in your dashboard."
            )
        else:
            summary_text = (
                f"{org_name} does not yet have sufficient evaluated evidence for a security score. "
                "Recorded open findings still require attention; missing evidence is not proof of security."
            )

    if not drivers:
        drivers = [{
            "impact": "No findings" if assessed else "Awaiting scan",
            "title": "No open findings" if assessed else "Insufficient assessment evidence",
            "desc": "The latest assessment has no open findings." if assessed else "Complete a scan to see findings here.",
            "remedy": "Continue monitoring your domains." if assessed else "Verify a domain and start a scan from your dashboard.",
        }]

    next_steps_heading = "OPEN FINDINGS AND NEXT STEPS" if assessed and any(
        d.get("impact") not in ("No findings", "Awaiting scan") for d in drivers
    ) else "ASSESSMENT STATUS" if assessed else "NEXT STEP"

    org_name = escape(org_name or "Organization")
    domain = escape(domain or "No verified domain")
    summary_text = escape(summary_text)

    scope_lines = [line for line in (coverage_label, domain_line, nuclei_line, *(integrity_lines or [])) if line]
    scope_html = ""
    if scope_lines:
        scope_items = "".join(
            f"""
            <div style="font-size: 13px; color: #3A352D; line-height: 1.6; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">{escape(line)}</div>"""
            for line in scope_lines
        )
        scope_html = f"""
      <!-- Declared Scope -->
      <tr>
        <td style="padding: 0 28px 22px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            SCOPE
          </div>
          <div style="padding: 12px 18px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-radius: 8px;">{scope_items}
          </div>
        </td>
      </tr>
"""

    drivers_html = ""
    for d in drivers:
        drivers_html += f"""
        <tr>
          <td style="padding: 13px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF;">
            <table cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr>
                <td style="vertical-align: top; width: 66px;">
                  <span style="display: inline-block; padding: 3px 8px; background-color: {d.get('badge_bg', '#F5F2EC')}; color: {d.get('badge_color', '#C2410C')}; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11px; font-weight: bold; border-radius: 10px; letter-spacing: 0.5px;">
                    {escape(str(d.get('impact') or '-'))}
                  </span>
                </td>
                <td style="vertical-align: top; padding-left: 10px;">
                  <div style="font-size: 14px; font-weight: 600; color: #1F1A14; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {escape(str(d.get('title') or 'Security issue'))}
                  </div>
                  <div style="font-size: 13px; color: #5D564B; line-height: 1.55; margin-bottom: 5px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {escape(str(d.get('desc') or ''))}
                  </div>
                  <div style="font-size: 12px; color: #C2410C; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    <strong>HOW TO FIX:</strong> {escape(str(d.get('remedy') or 'See your dashboard for details.'))}
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

    metric_items = [
        ("Assets on record", assets_count, "#1F1A14"),
        ("Open critical", critical_count, "#DC2626" if critical_count else "#059669"),
        ("Open high", high_count, "#D97706" if high_count else "#059669"),
        ("Open medium", medium_count, "#1F1A14"),
        ("Open low", low_count, "#1F1A14"),
        ("Resolved · 30 days", resolved_recent_count, "#047857"),
    ]
    metrics_html = ""
    for index in range(0, len(metric_items), 3):
        cells = "".join(
            f'<td class="report-metric-cell" width="33.33%" style="width:33.33%; padding:5px; vertical-align:top;">'
            f'<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#FAF9F6; border:1px solid #EFECE5; border-radius:8px;">'
            f'<tr><td style="padding:11px 8px; text-align:center;">'
            f'<div style="font-size:9px; color:#6B6459; text-transform:uppercase; letter-spacing:.5px;">{label}</div>'
            f'<div style="font-size:18px; font-weight:700; color:{color}; margin-top:4px;">{value}</div>'
            f'</td></tr></table></td>'
            for label, value, color in metric_items[index:index + 3]
        )
        metrics_html += f"<tr>{cells}</tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>Cyphward Security Report</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
    @media screen and (max-width: 600px) {{
      .report-outer {{ padding: 12px 0 !important; }}
      .report-card {{ width: 100% !important; border-radius: 0 !important; }}
      .report-pad {{ padding-left: 16px !important; padding-right: 16px !important; }}
      .report-header-status {{ display: none !important; }}
      .report-meta-cell {{ display: block !important; width: 100% !important; text-align: left !important; padding-top: 4px !important; }}
      .report-score-org, .report-score-value {{ display: block !important; width: 100% !important; text-align: left !important; }}
      .report-score-value {{ padding-top: 16px !important; }}
      .report-metric-cell {{ padding: 3px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-color-scheme: only light;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#F3F1EC;">
    {org_name} security report — score {score_label}, grade {grade_text}. {critical_count} urgent issues need attention. Open your dashboard for details.
  </div>
  <center class="report-outer" style="padding:24px 12px;">
    <table class="report-card" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 680px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">

      <!-- Amber Accent Bar -->
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>

      <!-- Header: Logo + Brand -->
      <tr>
        <td class="report-pad" style="padding: 22px 28px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="vertical-align: middle;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="vertical-align: middle; padding-right: 13px;">
                      <table cellpadding="0" cellspacing="0" border="0" bgcolor="#16130F" style="background-color: #16130F; border-radius: 10px;">
                        <tr>
                          <td style="padding: 6px 8px; font-size: 0; line-height: 0; text-align: center;">
                            <img src="https://cyphward.com/apple-touch-icon.png" alt="Cyphward" width="32" height="32" style="display: block; border: 0;" />
                          </td>
                        </tr>
                      </table>
                    </td>
                    <td style="vertical-align: middle;">
                      <div style="font-size: 18px; font-weight: 800; letter-spacing: 1.5px; color: #16130F;">
                        CYPH<span style="color: #E5532B;">WARD</span>
                      </div>
                      <div style="font-size: 10px; letter-spacing: 1.2px; color: #8A8377; text-transform: uppercase; margin-top: 2px;">
                        Security monitoring, made simple
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
              <td class="report-header-status" style="vertical-align: middle; text-align: right;">
                <span style="display: inline-block; padding: 5px 10px; background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 12px; font-size: 11px; font-weight: 600; color: #047857; letter-spacing: 0.3px;">
                  &#9679; {'Known-risk score available' if assessed else 'Insufficient assessment evidence'}
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Report Meta Strip -->
      <tr>
        <td class="report-pad" style="padding: 11px 28px; background-color: #FAF9F6; border-bottom: 1px solid #EFECE5;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td class="report-meta-cell" style="font-size: 11px; color: #C2410C; font-weight: 700; letter-spacing: 1px;">
                CONFIDENTIAL · SECURITY REPORT
              </td>
              <td class="report-meta-cell" style="text-align: right; font-size: 11px; color: #8A8377;">
                Website: <strong style="color: #1F1A14;">{domain}</strong>
                &nbsp;·&nbsp; Ref: <strong style="color: #8A8377;">CW-{report_ref}</strong>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Score Banner -->
      <tr>
        <td class="report-pad" style="padding: 22px 28px 6px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #FAF9F6; border: 1px solid #E6E2DA; border-radius: 10px; padding: 18px 20px;">
            <tr>
              <td class="report-score-org" style="vertical-align: middle;">
                <div style="font-size: 10px; color: #8A8377; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; font-weight: 600;">
                  Organization
                </div>
                <div style="font-size: 21px; font-weight: 700; color: #16130F; letter-spacing: -0.3px; margin-bottom: 4px;">
                  {org_name}
                </div>
                <div style="font-size: 13px; color: #6B6459; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                  A point-in-time view of known risks in the declared assessment scope
                </div>
              </td>
              <td class="report-score-value" style="vertical-align: middle; text-align: right; width: 150px;">
                <div style="font-size: 10px; color: #8A8377; letter-spacing: 1px; margin-bottom: 2px; font-weight: 600;">
                  SECURITY SCORE
                </div>
                <div style="font-size: 36px; font-weight: 800; color: {score_color}; line-height: 1; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;">
                  {score_text}<span style="font-size: 15px; color: #8A8377; font-weight: 400;">{score_suffix}</span>
                </div>
                <div style="margin-top: 7px;">
                  <span style="display: inline-block; padding: 3px 9px; background-color: #FFFFFF; border: 1px solid {score_color}; border-radius: 12px; font-size: 11px; font-weight: 700; color: {score_color};">
                    {grade_line}
                  </span>
                </div>
              </td>
            </tr>
            <tr>
              <td colspan="2" style="padding-top: 15px;">
                <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #ECE9E3; border-radius: 4px;">
                  <tr>
                    <td width="{score_width}%" style="background-color: {score_color}; border-radius: 4px; font-size: 0; line-height: 0;">&nbsp;</td>
                    <td style="font-size: 0; line-height: 0;">&nbsp;</td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Assessment metrics -->
      <tr>
        <td class="report-pad" style="padding: 12px 23px 18px;">
          <div style="padding:0 5px 5px; font-size:10px; color:#8A8377; letter-spacing:1px; font-weight:700;">ASSESSMENT AT A GLANCE</div>
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            {metrics_html}
          </table>
        </td>
      </tr>

      <!-- Plain-English Summary -->
      <tr>
        <td class="report-pad" style="padding: 0 28px 22px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            What we found
          </div>
          <div style="padding: 16px 18px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-left: 3px solid #E5532B; border-radius: 8px; font-size: 14px; color: #3A352D; line-height: 1.65; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            {summary_text}
          </div>
        </td>
      </tr>

{scope_html}
      <!-- Steps To Improve -->
      <tr>
        <td class="report-pad" style="padding: 0 28px 24px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            {next_steps_heading}
          </div>
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border: 1px solid #EFECE5; border-radius: 8px; overflow: hidden;">
            {drivers_html}
          </table>
        </td>
      </tr>

      <!-- CTA Button -->
      <tr>
        <td style="padding: 0 28px 8px; text-align: center;">
          <table cellpadding="0" cellspacing="0" border="0" align="center">
            <tr>
              <td style="background-color: #E5532B; border-radius: 8px; text-align: center;">
                <a href="https://app.cyphward.com/overview" target="_blank" style="display: inline-block; padding: 14px 32px; font-size: 14px; font-weight: 700; color: #FFFFFF; text-decoration: none; letter-spacing: 0.5px;">
                  Open your dashboard →
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding: 0 28px 26px; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: #6B6459; line-height: 1.5;">
          Review findings, assign remediation and verify supported fixes from your dashboard.
        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="padding: 18px 28px; background-color: #FAF9F6; border-top: 1px solid #EFECE5; font-size: 11px; color: #8A8377; line-height: 1.65;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td>
                <strong style="color: #5D564B;">CYPHWARD — EXTERNAL SECURITY MONITORING</strong><br />
                Findings and coverage reflect the checks listed in this report.<br />
                This report is not a compliance certification or guarantee of security.<br />
                Report <span style="color: #C2410C;">CW-{report_ref}</span> · Generated {generated_at} UTC.<br />
                You received this report because you manage <strong style="color: #5D564B;">{org_name}</strong>.
              </td>
              <td style="text-align: right; vertical-align: bottom;">
                <a href="https://cyphward.com/" target="_blank" style="color: #C2410C; text-decoration: underline;">cyphward.com</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

    </table>
  </center>
</body>
</html>
"""
    return html


def generate_welcome_email_html(user_name: str, login_email: str) -> str:
    """
    Renders the plain-English welcome email sent after signup or first login.
    Light theme, matches the executive report template.
    """
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    steps = [
        ("Create your organization", "Tell us your company or team name — this takes a few seconds."),
        ("Add and verify your domain", "Paste one DNS record so we can confirm your site belongs to you."),
        ("Run your first scan", "We check encryption, email security, headers, and exposure — then score it."),
    ]

    steps_html = ""
    for i, (title, desc) in enumerate(steps, start=1):
        steps_html += f"""
        <tr>
          <td style="padding: 14px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF; width: 44px; vertical-align: top;">
            <span style="display: inline-block; width: 26px; height: 26px; border-radius: 50%; background-color: #FFF3EC; border: 1px solid #F5D6C0; color: #C2410C; font-size: 13px; font-weight: 700; text-align: center; line-height: 26px;">{i}</span>
          </td>
          <td style="padding: 14px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF;">
            <div style="font-size: 14px; font-weight: 600; color: #1F1A14; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">{title}</div>
            <div style="font-size: 13px; color: #5D564B; line-height: 1.55; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">{desc}</div>
          </td>
        </tr>"""

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>Welcome to Cyphward</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-color-scheme: only light;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#F3F1EC;">
    Hi {first_name} — your Cyphward account is ready. Create your organization, verify your domain, and run your first scan.
  </div>
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 620px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">

      <!-- Amber Accent Bar -->
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>

      <!-- Header: Logo + Brand -->
      <tr>
        <td style="padding: 22px 28px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="vertical-align: middle;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="vertical-align: middle; padding-right: 13px;">
                      <table cellpadding="0" cellspacing="0" border="0" bgcolor="#16130F" style="background-color: #16130F; border-radius: 10px;">
                        <tr>
                          <td style="padding: 6px 8px; font-size: 0; line-height: 0; text-align: center;">
                            <img src="https://cyphward.com/apple-touch-icon.png" alt="Cyphward" width="32" height="32" style="display: block; border: 0;" />
                          </td>
                        </tr>
                      </table>
                    </td>
                    <td style="vertical-align: middle;">
                      <div style="font-size: 18px; font-weight: 800; letter-spacing: 1.5px; color: #16130F;">
                        CYPH<span style="color: #E5532B;">WARD</span>
                      </div>
                      <div style="font-size: 10px; letter-spacing: 1.2px; color: #8A8377; text-transform: uppercase; margin-top: 2px;">
                        Security monitoring, made simple
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
              <td style="vertical-align: middle; text-align: right;">
                <span style="display: inline-block; padding: 5px 10px; background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 12px; font-size: 11px; font-weight: 600; color: #047857; letter-spacing: 0.3px;">
                  &#9679; Account active
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Greeting -->
      <tr>
        <td style="padding: 26px 28px 6px;">
          <div style="font-size: 22px; font-weight: 700; color: #16130F; letter-spacing: -0.3px; margin-bottom: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            Welcome, {first_name}.
          </div>
          <div style="font-size: 14px; color: #3A352D; line-height: 1.65; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            Your Cyphward account is ready. In the next few minutes you can set up your organization,
            verify your domain, and get your first security score — no agents to install, nothing to configure.
          </div>
        </td>
      </tr>

      <!-- Steps -->
      <tr>
        <td style="padding: 16px 28px 4px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            Get started in 3 steps
          </div>
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border: 1px solid #EFECE5; border-radius: 8px; overflow: hidden;">
            {steps_html}
          </table>
        </td>
      </tr>

      <!-- CTA Button -->
      <tr>
        <td style="padding: 18px 28px 6px; text-align: center;">
          <table cellpadding="0" cellspacing="0" border="0" align="center">
            <tr>
              <td style="background-color: #E5532B; border-radius: 8px; text-align: center;">
                <a href="https://app.cyphward.com/overview" target="_blank" style="display: inline-block; padding: 14px 32px; font-size: 14px; font-weight: 700; color: #FFFFFF; text-decoration: none; letter-spacing: 0.5px;">
                  Open your dashboard →
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding: 0 28px 26px; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: #6B6459; line-height: 1.5;">
          Questions? Just reply to this email — a real person reads them.
        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="padding: 18px 28px; background-color: #FAF9F6; border-top: 1px solid #EFECE5; font-size: 11px; color: #8A8377; line-height: 1.65;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td>
                <strong style="color: #5D564B;">CYPHWARD — SECURITY MONITORING, MADE SIMPLE</strong><br />
                Continuous checks for your website, emails, and data protection.<br />
                You received this because an account was created for <strong style="color: #5D564B;">{login_email}</strong>.<br />
                Generated {generated_at} UTC.
              </td>
              <td style="text-align: right; vertical-align: bottom;">
                <a href="https://cyphward.com/" target="_blank" style="color: #C2410C; text-decoration: underline;">cyphward.com</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

    </table>
  </center>
</body>
</html>
"""
    return html


def generate_welcome_email_text(user_name: str, login_email: str) -> str:
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return (
        f"Hi {first_name},\n\n"
        "Welcome to Cyphward — your account is ready.\n\n"
        "Get started in 3 steps:\n"
        "1. Create your organization — tell us your company or team name.\n"
        "2. Add and verify your domain — paste one DNS record so we can confirm your site.\n"
        "3. Run your first scan — encryption, email security, headers, and exposure, scored.\n\n"
        "Open your dashboard: https://app.cyphward.com/overview\n\n"
        "Questions? Just reply to this email — a real person reads them.\n\n"
        "— Cyphward\n"
        "Security monitoring, made simple\n\n"
        f"You received this because an account was created for {login_email}."
    )


def generate_otp_email_html(user_name: str, code: str, minutes: int = 10) -> str:
    """
    Light-theme 6-digit verification code email (Brevo, plain English).
    Same visual language as the welcome/report templates.
    """
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>Your Cyphward verification code</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 24px 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-text-size-adjust: 100%;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; font-size:1px; line-height:1px; color:#F3F1EC;">
    Your Cyphward verification code is {code}. It expires in {minutes} minutes.
  </div>
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 520px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>
      <tr>
        <td style="padding: 26px 28px 30px;">
          <div style="font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: #8A8377; font-weight: 700; margin-bottom: 16px;">
            CYPH<span style="color: #E5532B;">WARD</span> &middot; EMAIL VERIFICATION
          </div>
          <div style="font-size: 15px; color: #1F1A14; line-height: 1.6; margin-bottom: 22px;">
            Hi {first_name}, enter this 6-digit code to verify your email address:
          </div>
          <div style="text-align: center; margin: 4px 0 24px;">
            <span style="display: inline-block; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 38px; font-weight: 700; letter-spacing: 12px; color: #16130F; background-color: #FFF7F2; border: 1px dashed #F0C9B4; border-radius: 10px; padding: 14px 6px 14px 18px;">{code}</span>
          </div>
          <div style="font-size: 13px; color: #5D564B; line-height: 1.6;">
            The code expires in {minutes} minutes. If the verification screen is open, the code
            fills the boxes automatically — the last digit submits it for you.
          </div>
          <div style="font-size: 13px; color: #5D564B; line-height: 1.6; margin-top: 12px;">
            Didn't request this? Ignore this email — nobody can access your account without it.
          </div>
        </td>
      </tr>
      <tr>
        <td style="padding: 14px 28px; border-top: 1px solid #EFECE5; background-color: #FBFAF7; font-size: 11px; color: #8A8377;">
          &mdash; Cyphward &middot; Security monitoring, made simple
        </td>
      </tr>
    </table>
  </center>
</body>
</html>
"""


def generate_otp_email_text(user_name: str, code: str, minutes: int = 10) -> str:
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return (
        f"Hi {first_name},\n\n"
        f"Your Cyphward verification code is: {code}\n\n"
        f"It expires in {minutes} minutes. Enter it on the verification screen — "
        "the last digit submits automatically.\n\n"
        "Didn't request this? Ignore this email; nobody can get in without it.\n\n"
        "— Cyphward\n"
        "Security monitoring, made simple"
    )


def generate_password_reset_email_html(user_name: str, reset_url: str, minutes: int = 30) -> str:
    """
    Password-reset link email (Brevo, plain English) — same visual language
    as the OTP template. Sent only when someone asks to reset a password.
    """
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>Reset your Cyphward password</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 24px 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-text-size-adjust: 100%;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; font-size:1px; line-height:1px; color:#F3F1EC;">
    Use the link below to reset your Cyphward password. It expires in {minutes} minutes.
  </div>
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 520px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>
      <tr>
        <td style="padding: 26px 28px 30px;">
          <div style="font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: #8A8377; font-weight: 700; margin-bottom: 16px;">
            CYPH<span style="color: #E5532B;">WARD</span> &middot; PASSWORD RESET
          </div>
          <div style="font-size: 15px; color: #1F1A14; line-height: 1.6; margin-bottom: 22px;">
            Hi {first_name}, someone asked to reset the password for this Cyphward account.
            Choose a new password using the button below:
          </div>
          <div style="text-align: center; margin: 4px 0 24px;">
            <a href="{reset_url}" style="display: inline-block; background-color: #E5532B; color: #FFFFFF; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 13px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; text-decoration: none; border-radius: 8px; padding: 14px 26px;">Reset password</a>
          </div>
          <div style="font-size: 13px; color: #5D564B; line-height: 1.6;">
            This link works once and expires in {minutes} minutes. After that, just request a new one.
          </div>
          <div style="font-size: 13px; color: #5D564B; line-height: 1.6; margin-top: 12px;">
            Didn't request this? Ignore this email — your password stays unchanged.
          </div>
        </td>
      </tr>
      <tr>
        <td style="padding: 14px 28px; border-top: 1px solid #EFECE5; background-color: #FBFAF7; font-size: 11px; color: #8A8377;">
          &mdash; Cyphward &middot; Security monitoring, made simple
        </td>
      </tr>
    </table>
  </center>
</body>
</html>
"""


def generate_password_reset_email_text(user_name: str, reset_url: str, minutes: int = 30) -> str:
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return (
        f"Hi {first_name},\n\n"
        "Someone asked to reset the password for your Cyphward account.\n\n"
        f"Reset it here: {reset_url}\n\n"
        f"The link works once and expires in {minutes} minutes.\n\n"
        "Didn't request this? Ignore this email; your password stays unchanged.\n\n"
        "— Cyphward\n"
        "Security monitoring, made simple"
    )


def generate_password_changed_alert_html(user_name: str) -> str:
    """Recovery alert: your password was just changed (credential-change notice)."""
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>Your Cyphward password was changed</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 24px 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-text-size-adjust: 100%;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; font-size:1px; line-height:1px; color:#F3F1EC;">
    The password for your Cyphward account was just changed.
  </div>
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 520px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>
      <tr>
        <td style="padding: 26px 28px 30px;">
          <div style="font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: #8A8377; font-weight: 700; margin-bottom: 16px;">
            CYPH<span style="color: #E5532B;">WARD</span> &middot; SECURITY ALERT
          </div>
          <div style="font-size: 15px; color: #1F1A14; line-height: 1.6; margin-bottom: 22px;">
            Hi {first_name}, the password for your Cyphward account was just changed,
            and all other sessions were signed out.
          </div>
          <div style="font-size: 13px; color: #5D564B; line-height: 1.6;">
            If this was you, no action is needed. If it wasn't you, request a new
            password-reset link immediately and contact support.
          </div>
        </td>
      </tr>
      <tr>
        <td style="padding: 14px 28px; border-top: 1px solid #EFECE5; background-color: #FBFAF7; font-size: 11px; color: #8A8377;">
          &mdash; Cyphward &middot; Security monitoring, made simple
        </td>
      </tr>
    </table>
  </center>
</body>
</html>
"""


def generate_password_changed_alert_text(user_name: str) -> str:
    first_name = (user_name or "").strip().split(" ")[0] or "there"
    return (
        f"Hi {first_name},\n\n"
        "The password for your Cyphward account was just changed, "
        "and all other sessions were signed out.\n\n"
        "If this was you, no action is needed. If it wasn't you, request a new "
        "password-reset link immediately and contact support.\n\n"
        "— Cyphward\n"
        "Security monitoring, made simple"
    )


_INVITE_ROLE_NOTES = {
    "owner": "You have full control of the workspace, including settings and membership.",
    "admin": "You can invite people, change settings, and manage findings.",
    "member": "You can view findings, scans, and reports.",
}


def generate_invite_email_html(
    inviter_name: str,
    invitee_name: str,
    invitee_email: str,
    org_name: str,
    role: str,
    accept_url: str,
) -> str:
    """
    Team-invite email (Brevo, plain English) — same visual language as the
    OTP/reset templates. Tells the invitee who invited them, their role,
    and how to get in.
    """
    inviter_first = (inviter_name or "A teammate").strip().split(" ")[0]
    invitee_first = (invitee_name or "").strip().split(" ")[0] or invitee_email.split("@")[0]
    role_note = _INVITE_ROLE_NOTES.get(role, _INVITE_ROLE_NOTES["member"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <meta name="format-detection" content="telephone=no">
  <title>You're invited to Cyphward</title>
  <style>
    html {{ color-scheme: only light; -webkit-color-scheme: only light; }}
    body {{ margin: 0; padding: 0; background-color: #F3F1EC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color-scheme: only light; -webkit-text-size-adjust: 100%; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-text-size-adjust: 100%;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; font-size:1px; line-height:1px; color:#F3F1EC;">
    {inviter_first} invited you to join {org_name} on Cyphward as {role}.
  </div>
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#FFFFFF" style="max-width: 520px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid #E6E2DA; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(31,26,20,0.08);">
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>
      <tr>
        <td style="padding: 26px 28px 30px;">
          <div style="font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: #8A8377; font-weight: 700; margin-bottom: 16px;">
            CYPH<span style="color: #E5532B;">WARD</span> &middot; TEAM INVITE
          </div>
          <div style="font-size: 20px; font-weight: 700; color: #16130F; letter-spacing: -0.3px; margin-bottom: 10px;">
            You're invited, {invitee_first}.
          </div>
          <div style="font-size: 14px; color: #3A352D; line-height: 1.65; margin-bottom: 14px;">
            <strong>{inviter_first}</strong> gave you <strong>{role}</strong> access to the
            <strong>{org_name}</strong> workspace on Cyphward.
          </div>
          <div style="padding: 12px 14px; background-color: #FFF7F2; border: 1px solid #F0C9B4; border-radius: 8px; font-size: 13px; color: #5D564B; line-height: 1.55; margin-bottom: 16px;">
            {role_note}
          </div>
          <div style="font-size: 14px; color: #3A352D; line-height: 1.65; margin-bottom: 20px;">
            Sign in with <strong>{invitee_email}</strong> to open the dashboard.
            New here? Create your account with this same email address first.
          </div>
          <div style="text-align: center; margin: 4px 0 8px;">
            <a href="{accept_url}" style="display: inline-block; background-color: #E5532B; color: #FFFFFF; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 13px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; text-decoration: none; border-radius: 8px; padding: 14px 26px;">Accept invitation</a>
          </div>
        </td>
        <td style="padding: 14px 28px; border-top: 1px solid #EFECE5; background-color: #FBFAF7; font-size: 11px; color: #8A8377;">
          &mdash; Cyphward &middot; Security monitoring, made simple
        </td>
      </tr>
      <tr>
        <td style="padding: 12px 28px; background-color: #FAF9F6; border-top: 1px solid #EFECE5; font-size: 11px; color: #8A8377; line-height: 1.6;">
          You received this because {inviter_first} invited <strong>{invitee_email}</strong> to {org_name}.
          Generated {generated_at} UTC.<br />
          <a href="https://cyphward.com/" target="_blank" style="color: #C2410C; text-decoration: underline;">cyphward.com</a>
        </td>
      </tr>
    </table>
  </center>
</body>
</html>
"""


def generate_invite_email_text(
    inviter_name: str,
    invitee_name: str,
    invitee_email: str,
    org_name: str,
    role: str,
    accept_url: str,
) -> str:
    inviter_first = (inviter_name or "A teammate").strip().split(" ")[0]
    invitee_first = (invitee_name or "").strip().split(" ")[0] or invitee_email.split("@")[0]
    role_note = _INVITE_ROLE_NOTES.get(role, _INVITE_ROLE_NOTES["member"])
    return (
        f"Hi {invitee_first},\n\n"
        f"{inviter_first} gave you {role} access to the {org_name} workspace on Cyphward.\n\n"
        f"{role_note}\n\n"
        f"Sign in with {invitee_email} to open the dashboard.\n"
        "New here? Create your account with this same email address first.\n\n"
        f"Accept: {accept_url}\n\n"
        "— Cyphward\n"
        "Security monitoring, made simple"
    )


async def send_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    recipient_name: Optional[str] = None,
    kind: str = DEFAULT_EMAIL_SENDER_KIND,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sends an email using Brevo REST API v3 with automatic failover to Brevo SMTP.

    `kind` selects the verified Brevo sender identity from EMAIL_SENDERS
    (system / alerts / reports / support / security / general).
    """
    to_email = to_email.strip()
    sender_name, sender_email = email_sender(kind)
    if not text_content:
        text_content = "Please view this Cyphward Security Report in an HTML-compatible email client."

    # 1. Primary Delivery Method: Brevo REST API v3
    if BREVO_API_KEY:
        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            payload = {
                "sender": {
                    "name": sender_name,
                    "email": sender_email,
                },
                "to": [
                    {
                        "email": to_email,
                        "name": recipient_name or to_email.split("@")[0],
                    }
                ],
                "subject": subject,
                "htmlContent": html_content,
                "textContent": text_content,
                "tracking": {"enabled": False, "opens": False, "clicks": False},
            }
            if reply_to:
                payload["replyTo"] = {"email": reply_to}

            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code in (200, 201, 202):
                    res_data = response.json()
                    logger.info(f"Email successfully dispatched via Brevo REST API to {to_email} (kind={kind}, from={sender_email}). Msg ID: {res_data.get('messageId')}")
                    return {
                        "success": True,
                        "method": "brevo_api",
                        "status_code": response.status_code,
                        "message_id": res_data.get("messageId"),
                        "recipient": to_email,
                    }
                else:
                    if response.status_code == 401:
                        # Auth/IP failure — the SMTP and Campaign tiers use the
                        # same egress IP, so failing over would only burn the
                        # 15s SMTP timeout on every recipient.
                        logger.warning(
                            f"Brevo REST API 401 for {to_email}: {response.text}. "
                            "Skipping SMTP/Campaign failover (same egress IP would be rejected)."
                        )
                        return {
                            "success": False,
                            "method": "brevo_api",
                            "status_code": 401,
                            "recipient": to_email,
                            "error": "unauthorised_ip",
                        }
                    logger.warning(f"Brevo REST API returned status {response.status_code}: {response.text}. Attempting SMTP failover...")
        except Exception as api_err:
            logger.warning(f"Brevo REST API call failed: {api_err}. Attempting SMTP failover...")

    # 2. Fallback Delivery Method: Brevo SMTP Relay
    smtp_err: Optional[Exception] = None
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to

        part1 = MIMEText(text_content, "plain", "utf-8")
        part2 = MIMEText(html_content, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        def _smtp_send() -> None:
            # smtplib is blocking: run it off the event loop so a slow mail
            # server can never freeze /health or hang the ASGI worker.
            with smtplib.SMTP(BREVO_SMTP_SERVER, BREVO_SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(BREVO_SMTP_LOGIN, BREVO_SMTP_PASSWORD)
                server.sendmail(sender_email, [to_email], msg.as_string())

        await asyncio.to_thread(_smtp_send)

        logger.info(f"Email successfully dispatched via Brevo SMTP relay to {to_email} (kind={kind}, from={sender_email})")
        return {
            "success": True,
            "method": "brevo_smtp",
            "recipient": to_email,
        }
    except Exception as err:
        smtp_err = err
        logger.warning(f"Brevo SMTP relay failed ({err}). Attempting Campaign API failover...")

    # 3. Third-Tier Delivery Method: Brevo Campaign Pipeline (bypasses unactivated SMTP relays)
    if BREVO_API_KEY:
        try:
            import time
            camp_headers = {
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Ensure recipient contact is registered in list 2
                await client.post(
                    "https://api.brevo.com/v3/contacts",
                    headers=camp_headers,
                    json={"email": to_email, "listIds": [2], "updateEnabled": True},
                )

                # Create targeted campaign
                camp_payload = {
                    "name": f"Cyphward Report - {to_email.split('@')[0]} - {int(time.time())}",
                    "subject": subject,
                    "sender": {"name": sender_name, "email": sender_email},
                    "type": "classic",
                    "htmlContent": html_content,
                    "recipients": {"listIds": [2]},
                }
                camp_res = await client.post(
                    "https://api.brevo.com/v3/emailCampaigns",
                    headers=camp_headers,
                    json=camp_payload,
                )
                if camp_res.status_code in (200, 201):
                    camp_id = camp_res.json().get("id")
                    # Trigger instant dispatch
                    send_res = await client.post(
                        f"https://api.brevo.com/v3/emailCampaigns/{camp_id}/sendNow",
                        headers=camp_headers,
                    )
                    if send_res.status_code in (200, 204):
                        logger.info(f"Email successfully dispatched via Brevo Campaign #{camp_id} to {to_email}")
                        return {
                            "success": True,
                            "method": "brevo_campaign",
                            "campaign_id": camp_id,
                            "recipient": to_email,
                        }

                logger.error(f"Brevo campaign creation failed: {camp_res.status_code} {camp_res.text}")
        except Exception as camp_err:
            logger.error(f"Brevo campaign failover error: {camp_err}")

    raise RuntimeError(
        f"All Brevo delivery methods (REST API, SMTP Relay, Campaign) failed to send to {to_email}. "
        f"Last SMTP error: {smtp_err}"
    )


def send_email_sync(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    recipient_name: Optional[str] = None,
    kind: str = DEFAULT_EMAIL_SENDER_KIND,
) -> Dict[str, Any]:
    """Synchronous wrapper for scripts and worker jobs.

    Request handlers must await send_email_async instead: this blocks the
    calling thread until delivery finishes. Delivery errors propagate as-is;
    they are never retried here.
    """
    import asyncio

    def deliver() -> Dict[str, Any]:
        # The coroutine is created inside the loop that runs it, so a failure
        # can never leave an un-awaited coroutine behind.
        return asyncio.run(
            send_email_async(to_email, subject, html_content, text_content, recipient_name, kind=kind)
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return deliver()  # No loop in this thread: run one.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(deliver).result()
