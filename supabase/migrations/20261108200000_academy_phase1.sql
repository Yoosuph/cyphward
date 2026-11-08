-- Cyphward Academy phase 1 (backend/app/academy, docs/academy-phase1-2026-11-08/README.md).
--
-- Courses written in the owner console and taken on academy.cyphward.com with the normal Cyphward account.
--
--   Content (owner console writes, learners read published courses only)
--     academy_courses          one row per course. status 'draft' or 'published'. price_minor and currency are kept
--                              for a later paid phase and are never shown or written in phase 1.
--     academy_modules          the course's sections, ordered by position.
--     academy_lessons          Markdown body (rendered as sanitised blocks, never as HTML) and an optional video
--                              embed URL that the API built from an allow-listed provider id.
--     academy_quizzes          a module's quizzes, with a pass mark (percent).
--     academy_quiz_questions   single or multiple choice.
--     academy_quiz_options     is_correct is read by the grader and the owner console only; learner reads never
--                              select it.
--     Content with learner records is archived (archived_at), never deleted: the history tables below refer to it
--     with ON DELETE RESTRICT, so a delete that would orphan history fails in the database too.
--
--   Learner history (append-only: the app role can read and add, never change or delete)
--     academy_enrolments        a person started a course.
--     academy_lesson_completions a person finished a lesson.
--     academy_quiz_attempts     every quiz submission with its server-side grade.
--     academy_certificates      issued once per person and course when every lesson is done and every quiz passed.
--                               `code` is the random public id of the verification page. The learner's name and
--                               the course title are frozen at issue.
--     A person's history goes when their account is deleted (profiles ON DELETE CASCADE), so a deleted account's
--     certificate no longer verifies.
--
--   Organisation assignments
--     academy_assignments      an owner or admin assigned a published course to a member, with an optional due
--                              date. The member must belong to the organisation: the composite foreign key to
--                              organization_members (user_id, org_id) enforces it, and removing the member removes
--                              the assignment. Unassigning sets removed_at (the row stays).
--
-- Seeds the two starter courses as UNPUBLISHED drafts for founder review (fixed ids, ON CONFLICT DO NOTHING, so
-- running this file again never duplicates or overwrites them).
--
-- Additive and idempotent. Locks are bounded by lock_timeout. Apply before the API that uses it is deployed.
--
-- Grants, following the notifications convention: REVOKE ALL first (Supabase's default privileges hand PUBLIC, anon
-- and authenticated ALL, TRUNCATE included, which row-level security does not stop; the app role's own default
-- privileges hand it SELECT, INSERT, UPDATE and DELETE on every new table), then only what the app needs.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- A table of this name existed in the pre-MVP schema (dropped by 20260922120000). Refuse to continue on a database
-- that still holds that old shape, instead of silently keeping it.
DO $$
BEGIN
  IF to_regclass('public.academy_courses') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'academy_courses' AND column_name = 'slug') THEN
    RAISE EXCEPTION 'A legacy academy_courses table is present; see docs/database-upgrade-runbook.md before applying.';
  END IF;
END $$;

-- ── Content ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS academy_courses (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug              text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 80),
  title             text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 160),
  summary           text NOT NULL DEFAULT '' CHECK (char_length(summary) <= 600),
  level             text NOT NULL DEFAULT 'beginner' CHECK (level IN ('beginner', 'intermediate', 'advanced')),
  duration_minutes  integer NOT NULL DEFAULT 30 CHECK (duration_minutes BETWEEN 1 AND 6000),
  cover_url         text CHECK (cover_url IS NULL OR (cover_url ~ '^https://[^\s]+$' AND char_length(cover_url) <= 500)),
  cover_alt         text NOT NULL DEFAULT '' CHECK (char_length(cover_alt) <= 200),
  price_minor       bigint CHECK (price_minor IS NULL OR price_minor >= 0),
  currency          text CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
  status            text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  published_at      timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'published' OR published_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_academy_courses_published ON academy_courses (published_at DESC) WHERE status = 'published';

CREATE TABLE IF NOT EXISTS academy_modules (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id    uuid NOT NULL REFERENCES academy_courses(id) ON DELETE CASCADE,
  position     integer NOT NULL DEFAULT 0 CHECK (position >= 0),
  title        text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 160),
  archived_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_modules_course_id_id_key UNIQUE (course_id, id)
);

CREATE TABLE IF NOT EXISTS academy_lessons (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id    uuid NOT NULL,
  module_id    uuid NOT NULL,
  position     integer NOT NULL DEFAULT 0 CHECK (position >= 0),
  title        text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 160),
  body_md      text NOT NULL DEFAULT '' CHECK (char_length(body_md) <= 40000),
  video_url    text CHECK (video_url IS NULL OR (video_url ~ '^https://[^\s]+$' AND char_length(video_url) <= 500)),
  minutes      integer NOT NULL DEFAULT 5 CHECK (minutes BETWEEN 1 AND 600),
  archived_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_lessons_course_id_id_key UNIQUE (course_id, id),
  CONSTRAINT academy_lessons_module_fkey FOREIGN KEY (course_id, module_id)
    REFERENCES academy_modules (course_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_academy_lessons_module ON academy_lessons (course_id, module_id, position);

CREATE TABLE IF NOT EXISTS academy_quizzes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id    uuid NOT NULL,
  module_id    uuid NOT NULL,
  position     integer NOT NULL DEFAULT 0 CHECK (position >= 0),
  title        text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 160),
  pass_mark    integer NOT NULL DEFAULT 70 CHECK (pass_mark BETWEEN 1 AND 100),
  archived_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_quizzes_course_id_id_key UNIQUE (course_id, id),
  CONSTRAINT academy_quizzes_module_fkey FOREIGN KEY (course_id, module_id)
    REFERENCES academy_modules (course_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_academy_quizzes_module ON academy_quizzes (course_id, module_id, position);

CREATE TABLE IF NOT EXISTS academy_quiz_questions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id    uuid NOT NULL,
  quiz_id      uuid NOT NULL,
  position     integer NOT NULL DEFAULT 0 CHECK (position >= 0),
  prompt       text NOT NULL CHECK (char_length(btrim(prompt)) BETWEEN 1 AND 600),
  kind         text NOT NULL DEFAULT 'single' CHECK (kind IN ('single', 'multiple')),
  explanation  text NOT NULL DEFAULT '' CHECK (char_length(explanation) <= 1000),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_quiz_questions_course_id_id_key UNIQUE (course_id, id),
  CONSTRAINT academy_quiz_questions_quiz_fkey FOREIGN KEY (course_id, quiz_id)
    REFERENCES academy_quizzes (course_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_academy_questions_quiz ON academy_quiz_questions (course_id, quiz_id, position);

CREATE TABLE IF NOT EXISTS academy_quiz_options (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id    uuid NOT NULL,
  question_id  uuid NOT NULL,
  position     integer NOT NULL DEFAULT 0 CHECK (position >= 0),
  label        text NOT NULL CHECK (char_length(btrim(label)) BETWEEN 1 AND 300),
  is_correct   boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_quiz_options_question_fkey FOREIGN KEY (course_id, question_id)
    REFERENCES academy_quiz_questions (course_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_academy_options_question ON academy_quiz_options (course_id, question_id, position);

-- ── Learner history (append-only) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS academy_enrolments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  course_id    uuid NOT NULL REFERENCES academy_courses(id) ON DELETE RESTRICT,
  enrolled_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_enrolments_user_course_key UNIQUE (user_id, course_id)
);
CREATE INDEX IF NOT EXISTS idx_academy_enrolments_course ON academy_enrolments (course_id, enrolled_at);

CREATE TABLE IF NOT EXISTS academy_lesson_completions (
  user_id       uuid NOT NULL,
  course_id     uuid NOT NULL,
  lesson_id     uuid NOT NULL,
  completed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, lesson_id),
  CONSTRAINT academy_lesson_completions_enrolment_fkey FOREIGN KEY (user_id, course_id)
    REFERENCES academy_enrolments (user_id, course_id) ON DELETE CASCADE,
  CONSTRAINT academy_lesson_completions_lesson_fkey FOREIGN KEY (course_id, lesson_id)
    REFERENCES academy_lessons (course_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_academy_completions_course ON academy_lesson_completions (course_id, user_id);

CREATE TABLE IF NOT EXISTS academy_quiz_attempts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL,
  course_id       uuid NOT NULL,
  quiz_id         uuid NOT NULL,
  answers         jsonb NOT NULL CHECK (jsonb_typeof(answers) = 'object' AND pg_column_size(answers) <= 32768),
  correct_count   integer NOT NULL CHECK (correct_count >= 0),
  question_count  integer NOT NULL CHECK (question_count >= 1 AND correct_count <= question_count),
  score_percent   integer NOT NULL CHECK (score_percent BETWEEN 0 AND 100),
  pass_mark       integer NOT NULL CHECK (pass_mark BETWEEN 1 AND 100),
  passed          boolean NOT NULL,
  submitted_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_quiz_attempts_enrolment_fkey FOREIGN KEY (user_id, course_id)
    REFERENCES academy_enrolments (user_id, course_id) ON DELETE CASCADE,
  CONSTRAINT academy_quiz_attempts_quiz_fkey FOREIGN KEY (course_id, quiz_id)
    REFERENCES academy_quizzes (course_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_academy_attempts_user_quiz ON academy_quiz_attempts (user_id, quiz_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_academy_attempts_course ON academy_quiz_attempts (course_id, quiz_id);

CREATE TABLE IF NOT EXISTS academy_certificates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code          text NOT NULL UNIQUE CHECK (code ~ '^[A-HJ-NP-Z2-9]{4}(-[A-HJ-NP-Z2-9]{4}){3}$'),
  user_id       uuid NOT NULL,
  course_id     uuid NOT NULL,
  learner_name  text NOT NULL CHECK (char_length(btrim(learner_name)) BETWEEN 1 AND 200),
  course_title  text NOT NULL CHECK (char_length(btrim(course_title)) BETWEEN 1 AND 160),
  completed_at  timestamptz NOT NULL,
  issued_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT academy_certificates_user_course_key UNIQUE (user_id, course_id),
  CONSTRAINT academy_certificates_enrolment_fkey FOREIGN KEY (user_id, course_id)
    REFERENCES academy_enrolments (user_id, course_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_academy_certificates_course ON academy_certificates (course_id, completed_at);

-- ── Organisation assignments ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS academy_assignments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  course_id    uuid NOT NULL REFERENCES academy_courses(id) ON DELETE RESTRICT,
  user_id      uuid NOT NULL,
  assigned_by  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  due_on       date,
  assigned_at  timestamptz NOT NULL DEFAULT now(),
  removed_at   timestamptz,
  removed_by   uuid REFERENCES profiles(id) ON DELETE SET NULL,
  CONSTRAINT academy_assignments_org_id_id_key UNIQUE (org_id, id),
  CONSTRAINT academy_assignments_member_fkey FOREIGN KEY (user_id, org_id)
    REFERENCES organization_members (user_id, org_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_academy_assignments_active
  ON academy_assignments (org_id, course_id, user_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_academy_assignments_user ON academy_assignments (user_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_academy_assignments_due ON academy_assignments (due_on) WHERE removed_at IS NULL AND due_on IS NOT NULL;

-- ── Row-level security and grants ──────────────────────────────────────────
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['academy_courses', 'academy_modules', 'academy_lessons', 'academy_quizzes',
                           'academy_quiz_questions', 'academy_quiz_options', 'academy_enrolments',
                           'academy_lesson_completions', 'academy_quiz_attempts', 'academy_certificates',
                           'academy_assignments'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS cyphward_app_all ON %I', t);
    EXECUTE format('CREATE POLICY cyphward_app_all ON %I FOR ALL TO cyphward_app USING (true) WITH CHECK (true)', t);
  END LOOP;
END $$;

REVOKE ALL ON academy_courses, academy_modules, academy_lessons, academy_quizzes, academy_quiz_questions, academy_quiz_options FROM PUBLIC;
REVOKE ALL ON academy_enrolments, academy_lesson_completions, academy_quiz_attempts, academy_certificates, academy_assignments FROM PUBLIC;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON academy_courses, academy_modules, academy_lessons, academy_quizzes, academy_quiz_questions, academy_quiz_options FROM %I', r);
      EXECUTE format('REVOKE ALL ON academy_enrolments, academy_lesson_completions, academy_quiz_attempts, academy_certificates, academy_assignments FROM %I', r);
    END IF;
  END LOOP;
END $$;

-- Content: the owner console adds, edits, reorders, archives, and deletes content that has no learner records.
-- price_minor and currency are not updatable in phase 1.
REVOKE ALL ON academy_courses, academy_modules, academy_lessons, academy_quizzes, academy_quiz_questions, academy_quiz_options FROM cyphward_app;
GRANT SELECT, INSERT, DELETE ON academy_courses, academy_modules, academy_lessons, academy_quizzes,
  academy_quiz_questions, academy_quiz_options TO cyphward_app;
GRANT UPDATE (title, summary, level, duration_minutes, cover_url, cover_alt, status, published_at, updated_at)
  ON academy_courses TO cyphward_app;
GRANT UPDATE (position, title, archived_at, updated_at) ON academy_modules TO cyphward_app;
GRANT UPDATE (position, title, body_md, video_url, minutes, archived_at, updated_at) ON academy_lessons TO cyphward_app;
GRANT UPDATE (position, title, pass_mark, archived_at, updated_at) ON academy_quizzes TO cyphward_app;
GRANT UPDATE (position, prompt, kind, explanation) ON academy_quiz_questions TO cyphward_app;
GRANT UPDATE (position, label, is_correct) ON academy_quiz_options TO cyphward_app;

-- Learner history: read and add only.
REVOKE ALL ON academy_enrolments, academy_lesson_completions, academy_quiz_attempts, academy_certificates FROM cyphward_app;
GRANT SELECT, INSERT ON academy_enrolments, academy_lesson_completions, academy_quiz_attempts, academy_certificates
  TO cyphward_app;

-- Assignments: read, add, change the due date and unassign (removed_at). Never deleted by the app.
REVOKE ALL ON academy_assignments FROM cyphward_app;
GRANT SELECT, INSERT ON academy_assignments TO cyphward_app;
GRANT UPDATE (due_on, removed_at, removed_by) ON academy_assignments TO cyphward_app;

-- ── Starter drafts for founder review (unpublished) ────────────────────────
-- General information only, not legal advice; every regulatory statement names its source. Section and article
-- numbers are left out on purpose until a practitioner has checked them.
INSERT INTO academy_courses (id, slug, title, summary, level, duration_minutes, status) VALUES
  ('ac000000-0000-4000-8000-000000000001', 'privacy-basics-for-staff', 'Privacy basics for staff',
   'A plain-English introduction to handling personal data at work, based on the Nigeria Data Protection Act 2023 and the NDPC''s General Application and Implementation Directive 2025. General information, not legal advice.',
   'beginner', 40, 'draft'),
  ('ac000000-0000-4000-8000-000000000002', 'email-and-website-security-basics', 'Email and website security basics',
   'How SPF, DKIM and DMARC protect your email domain, and how HTTPS and security headers protect your website visitors. Plain English for non-specialists.',
   'beginner', 45, 'draft')
ON CONFLICT (id) DO NOTHING;

INSERT INTO academy_modules (id, course_id, position, title) VALUES
  ('ac000000-0000-4000-8001-000000000011', 'ac000000-0000-4000-8000-000000000001', 0, 'Why personal data matters'),
  ('ac000000-0000-4000-8001-000000000012', 'ac000000-0000-4000-8000-000000000001', 1, 'Handling personal data day to day'),
  ('ac000000-0000-4000-8001-000000000021', 'ac000000-0000-4000-8000-000000000002', 0, 'Email you can trust'),
  ('ac000000-0000-4000-8001-000000000022', 'ac000000-0000-4000-8000-000000000002', 1, 'A safer website')
ON CONFLICT (id) DO NOTHING;

INSERT INTO academy_lessons (id, course_id, module_id, position, title, minutes, body_md) VALUES
  ('ac000000-0000-4000-8002-000000000111', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000011', 0,
   'What counts as personal data', 5, $md$## What counts as personal data

Personal data is any information that relates to a person who can be identified, directly or indirectly. Some everyday examples:

- a name, phone number or email address
- a home address or a staff ID number
- a photo, a voice recording or CCTV footage
- an IP address or a device identifier linked to someone

Some personal data is more sensitive, for example health information, religious beliefs or biometric data. It needs extra care.

## Why it matters at work

Customers, colleagues and suppliers trust you with their details. Careless handling can cause real harm: fraud, embarrassment or unfair treatment. Good habits protect people and your organisation.

> **General information, not legal advice.** Source: Nigeria Data Protection Act 2023 (NDPA), definitions of personal data and sensitive personal data.$md$),
  ('ac000000-0000-4000-8002-000000000112', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000011', 1,
   'The NDPA 2023 and the GAID 2025 in brief', 6, $md$## Two documents to know

**The Nigeria Data Protection Act 2023 (NDPA)** is the main law on personal data in Nigeria. It set up the Nigeria Data Protection Commission (NDPC), which oversees how organisations handle personal data.

**The General Application and Implementation Directive 2025 (GAID)** was issued by the NDPC. It explains in more detail how organisations are expected to apply the NDPA in practice, for example keeping records, assessing risky processing and making sure staff understand their part.

## What this means for you

You do not need to know the law by heart. You do need to:

1. handle personal data only for the job you are doing
2. keep it safe and share it only with people who need it
3. speak up quickly when something goes wrong

Your organisation decides its own policies and who you should ask. When in doubt, ask them.

> **General information, not legal advice.** Sources: Nigeria Data Protection Act 2023; NDPC General Application and Implementation Directive 2025.$md$),
  ('ac000000-0000-4000-8002-000000000121', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000012', 0,
   'The principles in plain English', 7, $md$## Seven habits behind the law

The NDPA sets out principles for handling personal data. In everyday terms:

1. **Be fair and open.** Tell people what you do with their data.
2. **Use it for a clear purpose.** Do not reuse data for something unrelated.
3. **Collect only what you need.** This is called data minimisation.
4. **Keep it accurate.** Correct mistakes when you find them.
5. **Keep it only as long as needed.** Follow your organisation's retention rules.
6. **Keep it secure.** Lock screens, use strong passwords and share files carefully.
7. **Be able to show your work.** Keep records of what you did and why.

## A lawful reason

Every use of personal data needs a lawful basis. The NDPA lists bases such as consent, a contract with the person, a legal obligation, protecting someone's vital interests, a task in the public interest, and legitimate interests.

> **General information, not legal advice.** Source: Nigeria Data Protection Act 2023, principles of processing and lawful bases.$md$),
  ('ac000000-0000-4000-8002-000000000122', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000012', 1,
   'People''s rights over their data', 6, $md$## Rights people can use

Under the NDPA, people can ask an organisation about the personal data it holds about them. Requests you may see include:

- **access:** "What do you hold about me?"
- **correction:** "This is wrong, please fix it."
- **deletion:** "Please delete my data."
- **objection or restriction:** "Please stop using my data for this."
- **withdrawing consent:** "I no longer agree."
- **data portability:** "Please give me my data in a usable format."

## What to do when you get a request

Do not try to handle it alone. Note the date, pass it to the person or team your organisation names for data requests, and do not delete or change anything until they reply. Requests have time limits, so pass them on the same day.

> **General information, not legal advice.** Source: Nigeria Data Protection Act 2023, rights of data subjects.$md$),
  ('ac000000-0000-4000-8002-000000000123', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000012', 2,
   'Spotting and reporting a data breach', 6, $md$## What a breach looks like

A personal data breach is any loss, theft or exposure of personal data, by accident or on purpose. Examples:

- an email with customer details sent to the wrong person
- a lost laptop or phone that holds work files
- a shared folder left open to anyone with the link
- someone signing in to a work account who should not

## Report it straight away

Tell the person or team your organisation names for data incidents as soon as you notice, even if you are not sure. Do not wait to investigate yourself.

Speed matters. The NDPA expects organisations to tell the NDPC within 72 hours of becoming aware of a breach that is likely to put people's rights at risk, and in some cases to tell the people affected.

> **General information, not legal advice.** Source: Nigeria Data Protection Act 2023, notification of personal data breaches.$md$),
  ('ac000000-0000-4000-8002-000000000211', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000021', 0,
   'How email spoofing works', 5, $md$## Anyone can write any "From" address

Email was designed decades ago, without a way to prove who sent a message. A criminal can put your organisation's address in the "From" line and send invoices, password resets or payment requests that look like yours.

Three DNS records help receiving mail servers tell real mail from fake mail:

- **SPF** lists the servers allowed to send for your domain
- **DKIM** adds a signature that proves a message was not changed
- **DMARC** tells receivers what to do when a message fails those checks

Cyphward's scans read these records for your verified domains and show what they find.

> Sources: RFC 7208 (SPF), RFC 6376 (DKIM) and RFC 7489 (DMARC), published by the IETF.$md$),
  ('ac000000-0000-4000-8002-000000000212', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000021', 1,
   'SPF: who may send for your domain', 6, $md$## A list of approved senders

An SPF record is a TXT record on your domain. It lists the mail services allowed to send email for you, for example your email provider and your newsletter tool.

    v=spf1 include:_spf.example.com ~all

The ending matters. `-all` asks receivers to reject mail from anyone not listed; `~all` asks them to treat it with suspicion.

## Common mistakes

- forgetting a service that sends on your behalf, so its mail fails
- publishing two SPF records (only one is allowed)
- going over the limit of ten DNS lookups

> Source: RFC 7208, Sender Policy Framework (SPF), IETF.$md$),
  ('ac000000-0000-4000-8002-000000000213', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000021', 2,
   'DKIM: signing your messages', 5, $md$## A signature on every message

DKIM lets your mail service add a cryptographic signature to each message it sends. The matching public key sits in your DNS. A receiving server checks the signature and can tell the message really came through your service and was not changed on the way.

## What you need to do

Your email provider usually gives you one or more DNS records to publish, often with a name like `selector._domainkey.yourdomain.com`. Publish them exactly as given, then switch DKIM signing on in the provider's settings. Do this for every service that sends mail for you.

> Source: RFC 6376, DomainKeys Identified Mail (DKIM) Signatures, IETF.$md$),
  ('ac000000-0000-4000-8002-000000000214', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000021', 3,
   'DMARC: a policy that ties them together', 7, $md$## Telling receivers what to do

DMARC is a TXT record at `_dmarc.yourdomain.com`. It tells receiving servers what to do with mail that fails SPF and DKIM checks for your domain, and where to send reports.

    v=DMARC1; p=none; rua=mailto:dmarc-reports@yourdomain.com

The policy `p=` has three values:

- `none`: only report, deliver as normal
- `quarantine`: treat failing mail as suspicious, for example the spam folder
- `reject`: refuse failing mail

## A safe path

Start with `p=none` and read the reports for a few weeks to find every service that sends for you. Fix their SPF and DKIM, then move to `quarantine` and later `reject`.

> Source: RFC 7489, Domain-based Message Authentication, Reporting, and Conformance (DMARC), IETF.$md$),
  ('ac000000-0000-4000-8002-000000000221', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000022', 0,
   'HTTPS and TLS certificates', 6, $md$## Why HTTPS

HTTPS encrypts the connection between a visitor's browser and your website, so others on the network cannot read or change what is sent, such as passwords or form details. Browsers mark plain HTTP pages as "Not secure".

## Keeping it working

- Use a TLS certificate from a trusted authority and renew it before it expires. Many hosts renew automatically.
- Send visitors from `http://` to `https://` with a permanent redirect.
- Turn off old protocol versions (TLS 1.0 and 1.1).

Cyphward's scans check certificate expiry dates and protocol versions on your verified domains.

> Sources: RFC 8446 (TLS 1.3), IETF; Mozilla's server-side TLS guidance.$md$),
  ('ac000000-0000-4000-8002-000000000222', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000022', 1,
   'Security headers', 7, $md$## Instructions your site sends to browsers

Security headers are short lines your web server adds to every response. They ask the browser to switch on protections:

- **Strict-Transport-Security (HSTS):** only connect to this site over HTTPS
- **Content-Security-Policy:** only load scripts and other content from sources you list
- **X-Content-Type-Options: nosniff:** do not guess file types
- **X-Frame-Options or frame-ancestors:** do not let other sites frame this page
- **Referrer-Policy:** limit what is shared about the page a visitor came from

## Where to start

HSTS and nosniff are quick wins. A Content-Security-Policy takes planning: start in report-only mode and tighten it over time.

> Sources: OWASP Secure Headers Project; MDN Web Docs on HTTP headers.$md$)
ON CONFLICT (id) DO NOTHING;

INSERT INTO academy_quizzes (id, course_id, module_id, position, title, pass_mark) VALUES
  ('ac000000-0000-4000-8003-000000000121', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8001-000000000012', 3,
   'Check your understanding', 75),
  ('ac000000-0000-4000-8003-000000000221', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8001-000000000022', 2,
   'Check your understanding', 75)
ON CONFLICT (id) DO NOTHING;

INSERT INTO academy_quiz_questions (id, course_id, quiz_id, position, kind, prompt, explanation) VALUES
  ('ac000000-0000-4000-8004-000000001211', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8003-000000000121', 0, 'single',
   'Which of these is personal data?', 'A phone number relates to a person who can be identified.'),
  ('ac000000-0000-4000-8004-000000001212', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8003-000000000121', 1, 'multiple',
   'Which of these are lawful bases listed in the NDPA? Choose all that apply.', 'Consent, a contract and a legal obligation are all listed. Data being easy to find is not a lawful basis.'),
  ('ac000000-0000-4000-8004-000000001213', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8003-000000000121', 2, 'single',
   'You think a laptop with customer records has been stolen. What should you do first?', 'Report it straight away. Time limits for notifying the NDPC start when the organisation becomes aware.'),
  ('ac000000-0000-4000-8004-000000001214', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8003-000000000121', 3, 'single',
   'What does data minimisation mean?', 'Collect and keep only what you need for the purpose.'),
  ('ac000000-0000-4000-8004-000000002211', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8003-000000000221', 0, 'single',
   'What does an SPF record list?', 'SPF lists the servers allowed to send email for your domain.'),
  ('ac000000-0000-4000-8004-000000002212', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8003-000000000221', 1, 'single',
   'What does DKIM add to each message?', 'DKIM adds a signature that receivers check against a public key in your DNS.'),
  ('ac000000-0000-4000-8004-000000002213', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8003-000000000221', 2, 'multiple',
   'Which of these are DMARC policy values? Choose all that apply.', 'The three policy values are none, quarantine and reject.'),
  ('ac000000-0000-4000-8004-000000002214', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8003-000000000221', 3, 'single',
   'What does the Strict-Transport-Security header ask browsers to do?', 'HSTS asks browsers to connect to the site over HTTPS only.')
ON CONFLICT (id) DO NOTHING;

INSERT INTO academy_quiz_options (id, course_id, question_id, position, label, is_correct) VALUES
  ('ac000000-0000-4000-8005-000012110001', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001211', 0, 'A customer''s phone number', true),
  ('ac000000-0000-4000-8005-000012110002', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001211', 1, 'The number of chairs in the office', false),
  ('ac000000-0000-4000-8005-000012110003', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001211', 2, 'The opening hours of the office', false),
  ('ac000000-0000-4000-8005-000012120001', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001212', 0, 'Consent', true),
  ('ac000000-0000-4000-8005-000012120002', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001212', 1, 'A contract with the person', true),
  ('ac000000-0000-4000-8005-000012120003', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001212', 2, 'The data was easy to find online', false),
  ('ac000000-0000-4000-8005-000012120004', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001212', 3, 'A legal obligation', true),
  ('ac000000-0000-4000-8005-000012130001', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001213', 0, 'Report it straight away to the person your organisation names for data incidents', true),
  ('ac000000-0000-4000-8005-000012130002', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001213', 1, 'Wait a week to see if it turns up', false),
  ('ac000000-0000-4000-8005-000012130003', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001213', 2, 'Look for it yourself before telling anyone', false),
  ('ac000000-0000-4000-8005-000012140001', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001214', 0, 'Collect and keep only what you need for the purpose', true),
  ('ac000000-0000-4000-8005-000012140002', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001214', 1, 'Store data in as few files as possible', false),
  ('ac000000-0000-4000-8005-000012140003', 'ac000000-0000-4000-8000-000000000001', 'ac000000-0000-4000-8004-000000001214', 2, 'Use small fonts in forms', false),
  ('ac000000-0000-4000-8005-000022110001', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002211', 0, 'The servers allowed to send email for your domain', true),
  ('ac000000-0000-4000-8005-000022110002', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002211', 1, 'The people who may read your email', false),
  ('ac000000-0000-4000-8005-000022110003', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002211', 2, 'The websites linked in your email', false),
  ('ac000000-0000-4000-8005-000022120001', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002212', 0, 'A cryptographic signature', true),
  ('ac000000-0000-4000-8005-000022120002', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002212', 1, 'A password for the attachment', false),
  ('ac000000-0000-4000-8005-000022120003', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002212', 2, 'A read receipt', false),
  ('ac000000-0000-4000-8005-000022130001', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002213', 0, 'none', true),
  ('ac000000-0000-4000-8005-000022130002', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002213', 1, 'quarantine', true),
  ('ac000000-0000-4000-8005-000022130003', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002213', 2, 'reject', true),
  ('ac000000-0000-4000-8005-000022130004', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002213', 3, 'block-all', false),
  ('ac000000-0000-4000-8005-000022140001', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002214', 0, 'Connect to the site over HTTPS only', true),
  ('ac000000-0000-4000-8005-000022140002', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002214', 1, 'Block all cookies on the site', false),
  ('ac000000-0000-4000-8005-000022140003', 'ac000000-0000-4000-8000-000000000002', 'ac000000-0000-4000-8004-000000002214', 2, 'Load the site faster', false)
ON CONFLICT (id) DO NOTHING;

COMMIT;
