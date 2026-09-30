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
    BREVO_SENDER_NAME,
    BREVO_SENDER_EMAIL,
)

logger = logging.getLogger("cyphward.mailer")


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
    Renders an authoritative, pixel-perfect HTML email template
    reflecting Cyphward's dark sovereign defense aesthetic.
    Compatible with Gmail, Apple Mail, Outlook, and webmail clients.
    """
    score_color = "#E5532B" if score < 70 else ("#D97706" if score < 85 else "#10B981")

    if not summary_text:
        summary_text = (
            f"{org_name}'s security score is {score} out of 100 (Grade {grade} — {posture_label}). "
            f"TLS 1.3 is active on public endpoints and no database ports are exposed. "
            f"However, weak email authentication (DMARC p=none) and a missing HSTS header "
            f"leave the domain open to spoofing and downgrade attacks. Fix steps are included below."
        )

    if not drivers:
        drivers = [
            {
                "impact": "-8 pts",
                "badge_bg": "#451A03",
                "badge_color": "#F97316",
                "title": "Weak email DMARC policy (p=none)",
                "desc": "Receiving mail servers accept spoofed emails without quarantining or rejecting them.",
                "remedy": "Set TXT record to v=DMARC1; p=reject; rua=mailto:dmarc@datagrid-ng.com.",
            },
            {
                "impact": "-8 pts",
                "badge_bg": "#451A03",
                "badge_color": "#F97316",
                "title": "HSTS header missing",
                "desc": "Subdomains still allow plain HTTP, which can be downgraded by attackers.",
                "remedy": "Add header Strict-Transport-Security: max-age=63072000; includeSubDomains; preload.",
            },
            {
                "impact": "+5 pts",
                "badge_bg": "#064E3B",
                "badge_color": "#34D399",
                "title": "Strong encryption (TLS 1.3) is active",
                "desc": "Modern ciphers protect connections to your public endpoints.",
                "remedy": "Keep as is. Continuous checks stay enabled.",
            },
        ]

    drivers_html = ""
    for d in drivers:
        drivers_html += f"""
        <tr>
          <td style="padding: 12px 14px; border-bottom: 1px solid #231E18; background-color: #14120E;">
            <table cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr>
                <td style="vertical-align: top; width: 68px;">
                  <span style="display: inline-block; padding: 3px 7px; background-color: {d.get('badge_bg', '#332415')}; color: {d.get('badge_color', '#F97316')}; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11px; font-weight: bold; border-radius: 4px; letter-spacing: 0.5px;">
                    {d.get('impact', '-')}
                  </span>
                </td>
                <td style="vertical-align: top; padding-left: 10px;">
                  <div style="font-size: 13px; font-weight: 600; color: #F5F2EB; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {d.get('title', 'Security Finding')}
                  </div>
                  <div style="font-size: 12px; color: #A8A095; line-height: 1.5; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                    {d.get('desc', '')}
                  </div>
                  <div style="font-size: 11px; color: #E5532B; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;">
                    ↳ FIX: {d.get('remedy', '')}
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
  <title>CYPHWARD Sovereign Executive Security Assessment</title>
  <style>
    body {{ margin: 0; padding: 0; background-color: #0A0907; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }}
    table {{ border-collapse: collapse; }}
  </style>
</head>
<body style="margin: 0; padding: 24px 0; background-color: #0A0907; color: #F5F2EB;">
  <center>
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width: 620px; margin: 0 auto; background-color: #12100C; border: 1px solid #2D271F; border-radius: 10px; overflow: hidden; box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
      
      <!-- Top Sovereign Accent Bar -->
      <tr>
        <td style="height: 4px; background: linear-gradient(90deg, #B33614, #E5532B, #FF8F6B, #E5532B); font-size: 0; line-height: 0;">&nbsp;</td>
      </tr>

      <!-- Header Section with Logo and Sovereign Defense Brand -->
      <tr>
        <td style="padding: 24px 28px 18px; border-bottom: 1px solid #231E18; background-color: #16130F;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="vertical-align: middle;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <!-- Cyphward Sovereign Shield SVG Mark -->
                    <td style="vertical-align: middle; padding-right: 12px;">
                      <img src="https://cyphward.com/shield-amber.png" alt="Cyphward Shield" width="34" height="34" style="display: block; border: 0;" />
                      <div style="width: 32px; height: 32px; border-radius: 6px; background-color: #26160E; border: 1px solid #E5532B; text-align: center; line-height: 30px; font-size: 16px; color: #E5532B; font-weight: bold;">
                        ⬡
                      </div>
                    </td>
                    <td style="vertical-align: middle;">
                      <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 16px; font-weight: 800; letter-spacing: 2px; color: #F5F2EB;">
                        CYPH<span style="color: #E5532B;">WARD</span>
                      </div>
                      <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 9px; letter-spacing: 1.5px; color: #A8A095; text-transform: uppercase;">
                        SOVEREIGN DEFENSE & RISK ENGINE
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
              <td style="vertical-align: middle; text-align: right;">
                <span style="display: inline-block; padding: 4px 8px; background-color: #1F1B15; border: 1px solid #332B20; border-radius: 4px; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #10B981; letter-spacing: 0.5px;">
                  ● ENCLAVE LIVE
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Classification & Target Strip -->
      <tr>
        <td style="padding: 12px 28px; background-color: #0E0C09; border-bottom: 1px solid #231E18;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #E5532B; font-weight: bold; letter-spacing: 1px;">
                CONFIDENTIAL // L00 BOARD ASSESSMENT
              </td>
              <td style="text-align: right; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #8C8477;">
                TARGET: <strong style="color: #F5F2EB;">{domain}</strong>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Executive Score & Posture Banner -->
      <tr>
        <td style="padding: 24px 28px; background-color: #14120E;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #1A1712; border: 1px solid #2F2820; border-radius: 8px; padding: 18px 20px;">
            <tr>
              <td style="vertical-align: middle;">
                <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #A8A095; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px;">
                  ORGANIZATION ENCLAVE
                </div>
                <div style="font-size: 20px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.3px; margin-bottom: 4px;">
                  {org_name}
                </div>
                <div style="font-size: 12px; color: #8C8477; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                  Security score based on DNS, web apps, encryption, and exposure
                </div>
              </td>
              <td style="vertical-align: middle; text-align: right; width: 140px;">
                <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #A8A095; letter-spacing: 1px; margin-bottom: 2px;">
                  SECURITY SCORE
                </div>
                <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 32px; font-weight: 800; color: {score_color}; line-height: 1;">
                  {score}<span style="font-size: 14px; color: #8C8477; font-weight: 400;">/100</span>
                </div>
                <div style="margin-top: 5px;">
                  <span style="display: inline-block; padding: 2px 7px; background-color: #26160E; border: 1px solid #E5532B; border-radius: 4px; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; font-weight: bold; color: #FF7A50;">
                    GRADE {grade} · {posture_label.upper()}
                  </span>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Key Metrics Row (4 Pillars) -->
      <tr>
        <td style="padding: 0 28px 20px;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td width="25%" style="padding: 10px 8px; background-color: #181510; border: 1px solid #262018; border-radius: 6px; text-align: center;">
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 9px; color: #8C8477; text-transform: uppercase;">MONITORED ASSETS</div>
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 16px; font-weight: 700; color: #F5F2EB; margin-top: 3px;">{assets_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 10px 8px; background-color: #181510; border: 1px solid #262018; border-radius: 6px; text-align: center;">
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 9px; color: #8C8477; text-transform: uppercase;">CRITICAL RISKS</div>
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 16px; font-weight: 700; color: {'#EF4444' if critical_count > 0 else '#10B981'}; margin-top: 3px;">{critical_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 10px 8px; background-color: #181510; border: 1px solid #262018; border-radius: 6px; text-align: center;">
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 9px; color: #8C8477; text-transform: uppercase;">HIGH FINDINGS</div>
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 16px; font-weight: 700; color: #F97316; margin-top: 3px;">{high_count}</div>
              </td>
              <td width="2%" style="font-size: 0;">&nbsp;</td>
              <td width="23%" style="padding: 10px 8px; background-color: #181510; border: 1px solid #262018; border-radius: 6px; text-align: center;">
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 9px; color: #8C8477; text-transform: uppercase;">NDPA 2023 SEC 39</div>
                <div style="font-family: 'SFMono-Regular', Consolas, monospace; font-size: 13px; font-weight: 700; color: #10B981; margin-top: 5px;">COMPLIANT</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Executive AI Narrative -->
      <tr>
        <td style="padding: 0 28px 24px;">
          <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11px; font-weight: bold; color: #A8A095; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            ✦ WHAT TO FIX FIRST
          </div>
          <div style="padding: 16px; background-color: #16130E; border: 1px solid #282119; border-left: 3px solid #E5532B; border-radius: 6px; font-size: 13px; color: #DDD7CD; line-height: 1.65; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            {summary_text}
          </div>
        </td>
      </tr>

      <!-- Prioritized Remediation Drivers -->
      <tr>
        <td style="padding: 0 28px 24px;">
          <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 11px; font-weight: bold; color: #A8A095; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px;">
            HOW TO IMPROVE YOUR SCORE
          </div>
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border: 1px solid #282119; border-radius: 6px; overflow: hidden;">
            {drivers_html}
          </table>
        </td>
      </tr>

      <!-- Primary Action CTA Button -->
      <tr>
        <td style="padding: 0 28px 30px; text-align: center;">
          <table cellpadding="0" cellspacing="0" border="0" align="center">
            <tr>
              <td style="background-color: #E5532B; border-radius: 6px; text-align: center;">
                <a href="https://cyphward.com/findings" target="_blank" style="display: inline-block; padding: 12px 28px; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 12px; font-weight: bold; color: #FFFFFF; text-decoration: none; letter-spacing: 1px; text-transform: uppercase;">
                  ACCESS COMMAND ENCLAVE →
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Statutory Disclaimer & Footer -->
      <tr>
        <td style="padding: 20px 28px; background-color: #0D0B08; border-top: 1px solid #231E18; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: 10px; color: #736B5E; line-height: 1.6;">
          <table cellpadding="0" cellspacing="0" border="0" width="100%">
            <tr>
              <td>
                <strong style="color: #A8A095;">CYPHWARD SOVEREIGN DEFENSE PLATFORM</strong><br />
                Deterministic Attack Surface Management & Statutory Cyber Resilience Engine.<br />
                Licensed under Nigerian Data Protection Act (NDPA 2023) & Central Bank of Nigeria (CBN) Risk Framework.<br />
                Enclave Telemetry Digest // Generated via Brevo Relay Dispatch.
              </td>
              <td style="text-align: right; vertical-align: bottom;">
                <span style="color: #E5532B;">SEC-ENC-2026</span>
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


async def send_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    recipient_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sends an email using Brevo REST API v3 with automatic failover to Brevo SMTP.
    """
    to_email = to_email.strip()
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
                    "name": BREVO_SENDER_NAME,
                    "email": BREVO_SENDER_EMAIL,
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
            }

            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code in (200, 201, 202):
                    res_data = response.json()
                    logger.info(f"Email successfully dispatched via Brevo REST API to {to_email}. Msg ID: {res_data.get('messageId')}")
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
        msg["From"] = f"{BREVO_SENDER_NAME} <{BREVO_SENDER_EMAIL}>"
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
                server.sendmail(BREVO_SENDER_EMAIL, [to_email], msg.as_string())

        await asyncio.to_thread(_smtp_send)

        logger.info(f"Email successfully dispatched via Brevo SMTP relay to {to_email}")
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
                    "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
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
                    send_email_async(to_email, subject, html_content, text_content, recipient_name)
                ).result()
        else:
            return loop.run_until_complete(
                send_email_async(to_email, subject, html_content, text_content, recipient_name)
            )
    except RuntimeError:
        return asyncio.run(
            send_email_async(to_email, subject, html_content, text_content, recipient_name)
        )
