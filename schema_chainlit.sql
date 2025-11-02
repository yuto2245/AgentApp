CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS "User" (
  id UUID PRIMARY KEY,
  identifier TEXT UNIQUE NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  "createdAt" TIMESTAMPTZ NOT NULL,
  "updatedAt" TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS "AppUser" (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'temporary',
  "email_token" TEXT,
  "token_expiry" TIMESTAMPTZ,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Thread" (
  id UUID PRIMARY KEY,
  name TEXT,
  "userId" UUID REFERENCES "User"(id) ON DELETE SET NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "deletedAt" TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS "Step" (
  id UUID PRIMARY KEY,
  "threadId" UUID REFERENCES "Thread"(id) ON DELETE CASCADE,
  "parentId" UUID REFERENCES "Step"(id) ON DELETE SET NULL,
  input JSONB,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  name TEXT,
  output JSONB,
  type TEXT NOT NULL,
  "startTime" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "endTime" TIMESTAMPTZ,
  "showInput" TEXT,
  "isError" BOOLEAN NOT NULL DEFAULT FALSE,
  "language" TEXT,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Element" (
  id UUID PRIMARY KEY,
  "threadId" UUID REFERENCES "Thread"(id) ON DELETE CASCADE,
  "stepId" UUID REFERENCES "Step"(id) ON DELETE CASCADE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  mime TEXT,
  name TEXT,
  "objectKey" TEXT,
  url TEXT,
  "chainlitKey" TEXT,
  display TEXT,
  size TEXT,
  language TEXT,
  page TEXT,
  "autoPlay" BOOLEAN,
  "playerConfig" JSONB,
  props JSONB,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Feedback" (
  id UUID PRIMARY KEY,
  "stepId" UUID REFERENCES "Step"(id) ON DELETE CASCADE,
  name TEXT,
  value DOUBLE PRECISION,
  comment TEXT,
  "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS thread_user_idx ON "Thread"("userId");
CREATE INDEX IF NOT EXISTS step_thread_idx ON "Step"("threadId");
CREATE INDEX IF NOT EXISTS element_thread_idx ON "Element"("threadId");
CREATE INDEX IF NOT EXISTS feedback_step_idx ON "Feedback"("stepId");
