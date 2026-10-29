// Generated from backend/app/core/newsletter.py render_issue() with the test draft (backend/tests/test_newsletter.py good_draft).
// Regenerate if the email template changes; the suite only needs realistic HTML for the sandboxed preview.
export const PREVIEW_DRAFT = {
  "subject": "Cyphward notes for October",
  "preview": "A product change, one security tip and a regulation update.",
  "sections": [
    {
      "type": "product",
      "heading": "Reports show the scan date",
      "body": "Every report now shows when the scan ran.",
      "links": [
        {
          "label": "See pricing",
          "url": "https://cyphward.com/pricing"
        }
      ]
    },
    {
      "type": "security_tip",
      "heading": "Publish a DMARC record",
      "body": "Start with p=none and read the reports.\nThen tighten it."
    },
    {
      "type": "regulation",
      "heading": "NDPC guidance note",
      "body": "The regulator published a guidance note on breach reporting.",
      "sources": [
        {
          "title": "NDPC guidance note",
          "url": "https://ndpc.gov.ng/guidance"
        }
      ]
    }
  ]
};
export const PREVIEW_HTML = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"color-scheme\" content=\"dark\"><meta name=\"supported-color-schemes\" content=\"dark\"><title>Cyphward notes for October</title></head><body style=\"margin:0;padding:0;background:#0A0907;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#F5F2EB\"><div style=\"display:none;max-height:0;overflow:hidden;opacity:0\">A product change, one security tip and a regulation update.</div><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"background:#0A0907\"><tr><td align=\"center\" style=\"padding:24px 12px\"><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"max-width:600px;background:#14130F;border:1px solid #24211A;border-radius:8px\"><tr><td style=\"height:4px;line-height:4px;font-size:4px;background:#E5532B;border-radius:8px 8px 0 0\">&nbsp;</td></tr><tr><td style=\"padding:22px 28px 8px\"><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr><td><table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\"><tr><td width=\"28\" height=\"28\" align=\"center\" valign=\"middle\" style=\"width:28px;height:28px;background:#E5532B;border-radius:6px;color:#0A0907;font-size:16px;font-weight:bold;line-height:28px;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif\">C</td><td style=\"padding-left:10px;font-size:15px;font-weight:bold;letter-spacing:.18em;color:#F5F2EB;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif\">CYPHWARD</td></tr></table></td><td align=\"right\" style=\"font-size:11px;letter-spacing:.2em;color:#A8A190;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif\">UPDATES</td></tr></table></td></tr><tr><td style=\"padding:12px 28px 12px;font-size:24px;line-height:1.3;font-weight:bold;color:#F5F2EB\">Cyphward notes for October</td></tr><tr><td style=\"padding:16px 28px 4px;border-top:1px solid #24211A\"><p style=\"margin:0 0 4px;font-size:11px;letter-spacing:.16em;color:#E5532B\">PRODUCT</p><h2 style=\"margin:0 0 10px;font-size:18px;line-height:1.35;color:#F5F2EB\">Reports show the scan date</h2><div style=\"font-size:15px;line-height:1.6;color:#F5F2EB\"><p style=\"margin:0 0 12px\">Every report now shows when the scan ran.</p><ul style=\"margin:0 0 12px;padding-left:18px\"><li style=\"margin:0 0 6px\"><a href=\"https://cyphward.com/pricing\" style=\"color:#F27350;text-decoration:underline\">See pricing</a></li></ul></div></td></tr><tr><td style=\"padding:16px 28px 4px;border-top:1px solid #24211A\"><p style=\"margin:0 0 4px;font-size:11px;letter-spacing:.16em;color:#E5532B\">SECURITY TIP</p><h2 style=\"margin:0 0 10px;font-size:18px;line-height:1.35;color:#F5F2EB\">Publish a DMARC record</h2><div style=\"font-size:15px;line-height:1.6;color:#F5F2EB\"><p style=\"margin:0 0 12px\">Start with p=none and read the reports.</p><p style=\"margin:0 0 12px\">Then tighten it.</p></div></td></tr><tr><td style=\"padding:16px 28px 4px;border-top:1px solid #24211A\"><p style=\"margin:0 0 4px;font-size:11px;letter-spacing:.16em;color:#E5532B\">REGULATION</p><h2 style=\"margin:0 0 10px;font-size:18px;line-height:1.35;color:#F5F2EB\">NDPC guidance note</h2><div style=\"font-size:15px;line-height:1.6;color:#F5F2EB\"><p style=\"margin:0 0 12px\">The regulator published a guidance note on breach reporting.</p><p style=\"margin:0 0 6px;font-size:11px;letter-spacing:.16em;color:#A8A190\">SOURCES</p><ul style=\"margin:0 0 12px;padding-left:18px;font-size:13px\"><li style=\"margin:0 0 6px\"><a href=\"https://ndpc.gov.ng/guidance\" style=\"color:#F27350;text-decoration:underline\">NDPC guidance note</a></li></ul></div></td></tr><tr><td style=\"padding:20px 28px 28px;border-top:1px solid #24211A;font-size:12px;line-height:1.6;color:#A8A190\"><p style=\"margin:0 0 8px;color:#A8A190\">You are receiving this because you subscribed to Cyphward updates.</p><p style=\"margin:0 0 8px;color:#A8A190\"><a href=\"https://cyphward.com/api/v1/newsletter/unsubscribe?token=PREVIEW\" style=\"color:#F27350;text-decoration:underline\">Unsubscribe in one click</a> (no sign-in needed).</p><p style=\"margin:0 0 8px;color:#A8A190\">Cyphward is not a law firm. Regulation updates are general information, not legal advice.</p><p style=\"margin:0;color:#A8A190\">Cyphward Ltd, RC 9921694, Kano, Nigeria. info@cyphward.com</p></td></tr></table></td></tr></table></body></html>";
export const PREVIEW_TEXT = "Cyphward notes for October\n\nA product change, one security tip and a regulation update.\n\nPRODUCT: Reports show the scan date\n\nEvery report now shows when the scan ran.\n- See pricing: https://cyphward.com/pricing\n\nSECURITY TIP: Publish a DMARC record\n\nStart with p=none and read the reports.\nThen tighten it.\n\nREGULATION: NDPC guidance note\n\nThe regulator published a guidance note on breach reporting.\nSource: NDPC guidance note: https://ndpc.gov.ng/guidance\n\nYou are receiving this because you subscribed to Cyphward updates.\nUnsubscribe in one click: https://cyphward.com/api/v1/newsletter/unsubscribe?token=PREVIEW\nCyphward is not a law firm. Regulation updates are general information, not legal advice.\nCyphward Ltd, RC 9921694, Kano, Nigeria. info@cyphward.com";
