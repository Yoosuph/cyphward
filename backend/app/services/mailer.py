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
    org_name: str = "DataGrid Africa",
    domain: str = "datagrid-ng.com",
    score: int = 76,
    grade: str = "B",
    posture_label: str = "Good",
    assets_count: int = 18,
    critical_count: int = 0,
    high_count: int = 3,
    medium_count: int = 0,
    summary_text: Optional[str] = None,
    drivers: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Renders a clean, light-themed HTML security report email in plain English.
    Compatible with Gmail, Apple Mail, Outlook, and webmail clients.
    """
    score_color = "#DC2626" if score < 70 else ("#D97706" if score < 85 else "#059669")
    report_ref = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    score_width = max(2, min(100, int(score)))

    if not summary_text:
        summary_text = (
            f"We checked {domain} and gave {org_name} a security score of {score} out of 100 "
            f"(grade {grade} — {posture_label}). The good news: your site is reachable and mostly healthy. "
            f"The issues below are the quickest wins — each takes a few minutes to fix and will raise your "
            f"score right away. Step-by-step guides are inside your dashboard."
        )

    if not drivers:
        drivers = [
            {
                "impact": "-8 pts",
                "badge_bg": "#FFF3EC",
                "badge_color": "#C2410C",
                "title": "Anyone can send fake emails as you",
                "desc": "Without a strict DMARC rule, scammers can send emails that look like they come from your domain — which hurts your customers' trust.",
                "remedy": "Set DMARC to reject unknown senders. Your dashboard shows the exact record to paste.",
            },
            {
                "impact": "-8 pts",
                "badge_bg": "#FFF3EC",
                "badge_color": "#C2410C",
                "title": "Some pages can load without encryption",
                "desc": "A visitor could accidentally reach an unencrypted version of your site, which is easier for anyone on the same network to snoop on.",
                "remedy": "Turn on HSTS (one switch) so every visit stays encrypted.",
            },
            {
                "impact": "+5 pts",
                "badge_bg": "#EAF9F1",
                "badge_color": "#0B7A53",
                "title": "Strong encryption is working",
                "desc": "Data between your visitors and your servers is securely encrypted.",
                "remedy": "Nothing to do — we keep watching it for you.",
            },
        ]

    drivers_html = ""
    for d in drivers:
        drivers_html += f"""
        <tr>
          <td style="padding: 13px 16px; border-bottom: 1px solid #EFECE5; background-color: #FFFFFF;">
            <table cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr>
                <td style="vertical-align: top; width: 66px;">
                  <span style="display: inline-block; padding: 3px 8px; background-color: {d.get('badge_bg', '#F5F2EC')}; color: {d.get('badge_color', '#C2410C')}; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11px; font-weight: bold; border-radius: 10px; letter-spacing: 0.5px;">
                    {d.get('impact', '-')}
                  </span>
                </td>
                <td style="vertical-align: top; padding-left: 10px;">
                  <div style="font-size: 14px; font-weight: 600; color: #1F1A14; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {d.get('title', 'Security issue')}
                  </div>
                  <div style="font-size: 13px; color: #5D564B; line-height: 1.55; margin-bottom: 5px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {d.get('desc', '')}
                  </div>
                  <div style="font-size: 12px; color: #C2410C; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    <strong>HOW TO FIX:</strong> {d.get('remedy', '')}
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """

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
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #F3F1EC; color: #1F1A14; color-scheme: only light; -webkit-color-scheme: only light;" bgcolor="#F3F1EC">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; font-size:1px; line-height:1px; color:#F3F1EC;">
    {org_name} security report — score {score}/100, grade {grade}. {critical_count} urgent issues need attention. Open your dashboard for details.
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
                  &#9679; Monitoring active
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Report Meta Strip -->
      <tr>
        <td style="padding: 11px 28px; background-color: #FAF9F6; border-bottom: 1px solid #EFECE5;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="font-size: 11px; color: #C2410C; font-weight: 700; letter-spacing: 1px;">
                CONFIDENTIAL · SECURITY REPORT
              </td>
              <td style="text-align: right; font-size: 11px; color: #8A8377;">
                Website: <strong style="color: #1F1A14;">{domain}</strong>
                &nbsp;·&nbsp; Ref: <strong style="color: #8A8377;">CW-{report_ref}</strong>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Score Banner -->
      <tr>
        <td style="padding: 22px 28px 6px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #FAF9F6; border: 1px solid #E6E2DA; border-radius: 10px; padding: 18px 20px;">
            <tr>
              <td style="vertical-align: middle;">
                <div style="font-size: 10px; color: #8A8377; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; font-weight: 600;">
                  Organization
                </div>
                <div style="font-size: 21px; font-weight: 700; color: #16130F; letter-spacing: -0.3px; margin-bottom: 4px;">
                  {org_name}
                </div>
                <div style="font-size: 13px; color: #6B6459; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                  How safe your public-facing systems are right now
                </div>
              </td>
              <td style="vertical-align: middle; text-align: right; width: 150px;">
                <div style="font-size: 10px; color: #8A8377; letter-spacing: 1px; margin-bottom: 2px; font-weight: 600;">
                  SECURITY SCORE
                </div>
                <div style="font-size: 36px; font-weight: 800; color: {score_color}; line-height: 1; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;">
                  {score}<span style="font-size: 15px; color: #8A8377; font-weight: 400;">/100</span>
                </div>
                <div style="margin-top: 7px;">
                  <span style="display: inline-block; padding: 3px 9px; background-color: #FFFFFF; border: 1px solid {score_color}; border-radius: 12px; font-size: 11px; font-weight: 700; color: {score_color};">
                    Grade {grade} · {posture_label}
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

      <!-- Key Numbers Row -->
      <tr>
        <td style="padding: 16px 28px 18px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td width="25%" style="padding: 11px 6px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-radius: 8px; text-align: center;">
                <div style="font-size: 9px; color: #8A8377; text-transform: uppercase; letter-spacing: 0.5px;">Systems checked</div>
                <div style="font-size: 17px; font-weight: 700; color: #1F1A14; margin-top: 4px;">{assets_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 11px 6px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-radius: 8px; text-align: center;">
                <div style="font-size: 9px; color: #8A8377; text-transform: uppercase; letter-spacing: 0.5px;">Urgent issues</div>
                <div style="font-size: 17px; font-weight: 700; color: {'#DC2626' if critical_count > 0 else '#059669'}; margin-top: 4px;">{critical_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 11px 6px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-radius: 8px; text-align: center;">
                <div style="font-size: 9px; color: #8A8377; text-transform: uppercase; letter-spacing: 0.5px;">Serious issues</div>
                <div style="font-size: 17px; font-weight: 700; color: {'#D97706' if high_count > 0 else '#059669'}; margin-top: 4px;">{high_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 11px 6px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-radius: 8px; text-align: center;">
                <div style="font-size: 9px; color: #8A8377; text-transform: uppercase; letter-spacing: 0.5px;">NDPA compliance</div>
                <div style="font-size: 13px; font-weight: 700; color: #059669; margin-top: 6px;">COMPLIANT</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Plain-English Summary -->
      <tr>
        <td style="padding: 0 28px 22px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            What we found
          </div>
          <div style="padding: 16px 18px; background-color: #FAF9F6; border: 1px solid #EFECE5; border-left: 3px solid #E5532B; border-radius: 8px; font-size: 14px; color: #3A352D; line-height: 1.65; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            {summary_text}
          </div>
        </td>
      </tr>

      <!-- Steps To Improve -->
      <tr>
        <td style="padding: 0 28px 24px;">
          <div style="font-size: 12px; font-weight: 700; color: #6B6459; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            HOW TO IMPROVE YOUR SCORE
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
                <a href="https://cyphward.com/" target="_blank" style="display: inline-block; padding: 14px 32px; font-size: 14px; font-weight: 700; color: #FFFFFF; text-decoration: none; letter-spacing: 0.5px;">
                  Open your dashboard →
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding: 0 28px 26px; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: #6B6459; line-height: 1.5;">
          See every detail, track your fixes, and re-check your site any time.
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
                Prepared for the Nigerian Data Protection Act (NDPA 2023) &amp; CBN risk standards.<br />
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
                <a href="https://cyphward.com/" target="_blank" style="display: inline-block; padding: 14px 32px; font-size: 14px; font-weight: 700; color: #FFFFFF; text-decoration: none; letter-spacing: 0.5px;">
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
        "Open your dashboard: https://cyphward.com/\n\n"
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
    """Synchronous wrapper for scripts and worker jobs."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In running event loop (e.g. jupyter or async runner)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    send_email_async(to_email, subject, html_content, text_content, recipient_name, kind=kind)
                ).result()
        else:
            return loop.run_until_complete(
                send_email_async(to_email, subject, html_content, text_content, recipient_name, kind=kind)
            )
    except RuntimeError:
        return asyncio.run(
            send_email_async(to_email, subject, html_content, text_content, recipient_name, kind=kind)
        )
