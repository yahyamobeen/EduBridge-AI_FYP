-- ============================================================================
-- EduBridge AI — Subscriptions + OAuth identities
-- Implements  : prd.md §Monetisation (v0.3.2), tdd.md §5.4
--
-- WHY THIS MIGRATION
--   Two decisions taken after the initial schema was applied:
--     1. Access is paid — a single tier at Rs. 999/month, no free tier, with
--        a 14-day trial. This adds the derived onboarding_state value
--        `plan_selection_pending` (students only, after the guardian gate).
--     2. Social sign-in (Google / Microsoft) is planned but NOT built in this
--        sprint. The identity table lands now so the schema is stable when it
--        is; nothing writes to it yet.
--
-- ON onboarding_state
--   It is a DERIVED API field, not a column. It is computed from
--   app_user.email_verified_at, two_factor_enrollment.status,
--   guardian_link.status and now subscription.status. Nothing to ALTER here.
--
--   IMPORTANT for the backend: a student MUST get a subscription row at
--   registration (status 'trialing'). The absence of a row is NOT the same as
--   "trialing" — derive it fail-closed (no row => no access), so a failed
--   insert can never silently grant free access forever.
--
-- NOTE
--   Never edit an applied migration; this is additive only.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Enumerated types
-- ----------------------------------------------------------------------------
CREATE TYPE subscription_status AS ENUM ('trialing','active','past_due','canceled','expired');
CREATE TYPE oauth_provider      AS ENUM ('google','microsoft');

-- ============================================================================
-- 1. SUBSCRIPTION PLANS                                          (tdd §5.4)
-- Reference data. One row today; the table exists so adding a tier later is
-- data, not a migration.
-- ============================================================================

CREATE TABLE public.subscription_plan (
  code             text        PRIMARY KEY,
  name             text        NOT NULL,
  -- Minor units (paisa) so money is never a float. Rs. 999.00 = 99900.
  price_minor      integer     NOT NULL CHECK (price_minor > 0),
  currency         char(3)     NOT NULL DEFAULT 'PKR' CHECK (currency ~ '^[A-Z]{3}$'),
  -- 'interval' is a type name in Postgres; prefixed to avoid the ambiguity,
  -- same reasoning as app_user vs the reserved "user".
  billing_interval text        NOT NULL DEFAULT 'month' CHECK (billing_interval IN ('month','year')),
  is_active        boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_subscription_plan_updated BEFORE UPDATE ON public.subscription_plan
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

-- ============================================================================
-- 2. SUBSCRIPTIONS                                               (tdd §5.4)
-- One per user. Students only in v1, but not constrained to role here: the
-- role check belongs in the service layer, and a CHECK against app_user.role
-- is not possible in a row constraint anyway.
-- ============================================================================

CREATE TABLE public.subscription (
  id                 uuid                PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid                NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  plan_code          text                NOT NULL REFERENCES public.subscription_plan(code),
  status             subscription_status NOT NULL DEFAULT 'trialing',
  -- 14-day trial. THIS DEFAULT IS THE SOURCE OF TRUTH for trial length —
  -- the application must not carry its own copy of the number.
  trial_ends_at      timestamptz         NOT NULL DEFAULT (now() + interval '14 days'),
  current_period_end timestamptz,
  created_at         timestamptz         NOT NULL DEFAULT now(),
  updated_at         timestamptz         NOT NULL DEFAULT now(),

  CONSTRAINT uq_subscription_user UNIQUE (user_id),
  -- A paid subscription must say when the paid period ends, or renewal and
  -- expiry sweeps have nothing to key on.
  CONSTRAINT ck_subscription_active_has_period
    CHECK (status <> 'active' OR current_period_end IS NOT NULL)
);
CREATE TRIGGER trg_subscription_updated BEFORE UPDATE ON public.subscription
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

-- Drives the sweeper that flips expired trials -> 'expired', which is what
-- puts a student into plan_selection_pending.
CREATE INDEX ix_subscription_trial_end ON public.subscription(trial_ends_at)
  WHERE status = 'trialing';
CREATE INDEX ix_subscription_period_end ON public.subscription(current_period_end)
  WHERE status = 'active';

-- ============================================================================
-- 3. OAUTH IDENTITIES                                            (tdd §5.4)
-- Reserved for the deferred social sign-in feature. No writer exists yet.
-- ============================================================================

CREATE TABLE public.oauth_identity (
  id               uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid           NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  provider         oauth_provider NOT NULL,
  -- The provider's subject claim ('sub'). Opaque, not an email: emails change
  -- and are reusable, subjects are not.
  provider_user_id text           NOT NULL,
  created_at       timestamptz    NOT NULL DEFAULT now(),

  -- One external identity maps to exactly one local account.
  CONSTRAINT uq_oauth_provider_subject UNIQUE (provider, provider_user_id),
  -- ...and a user links a given provider at most once.
  CONSTRAINT uq_oauth_user_provider    UNIQUE (user_id, provider)
);

-- ============================================================================
-- 4. SEED
-- ============================================================================

INSERT INTO public.subscription_plan (code, name, price_minor, currency, billing_interval)
VALUES ('standard', 'EduBridge AI', 99900, 'PKR', 'month');

-- ============================================================================
-- 5. GRANTS
-- ALTER DEFAULT PRIVILEGES in the RLS migration should cover these, but that
-- only applies to tables created by the same role. Explicit and idempotent.
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE
  ON public.subscription_plan, public.subscription, public.oauth_identity
  TO app_backend;

-- ============================================================================
-- 6. ROW LEVEL SECURITY
-- FORCE is what makes these real: without it the table owner bypasses every
-- policy below and they become decorative.
-- ============================================================================

ALTER TABLE public.subscription_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_plan FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.subscription      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription      FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.oauth_identity    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_identity    FORCE  ROW LEVEL SECURITY;

-- Plans are reference data: any signed-in user may read them (the plan screen
-- is shown while onboarding_state = 'plan_selection_pending', so a session
-- always exists). Only admins may change them.
CREATE POLICY subscription_plan_read ON public.subscription_plan
  FOR SELECT TO app_backend
  USING (app.current_user_id() IS NOT NULL);

CREATE POLICY subscription_plan_admin_write ON public.subscription_plan
  FOR ALL TO app_backend
  USING (app.is_admin()) WITH CHECK (app.is_admin());

-- A subscription is the subscriber's own row and nobody else's.
-- Deliberately NO parent policy: parents pay for nothing in v1 (plan selection
-- is students-only), and inventing guardian read access here would widen the
-- RBAC matrix in prd.md §4.2 without a requirement behind it. Add it in its
-- own migration if and when parent-pays is specced.
CREATE POLICY subscription_owner ON public.subscription
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

-- Admins get READ only, for provisioning and billing support (FR-K1).
-- Not FOR ALL: an admin must not be able to silently grant themselves or
-- anyone else a paid subscription without going through the payment path.
CREATE POLICY subscription_admin_read ON public.subscription
  FOR SELECT TO app_backend
  USING (app.is_admin());

-- Owner-only, mirroring two_factor_enrollment. No admin policy: provider_user_id
-- is an identifying external subject, and admins have no support workflow that
-- needs it. Unlinking is done by the user.
CREATE POLICY oauth_identity_owner ON public.oauth_identity
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());
