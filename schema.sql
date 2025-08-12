BEGIN;

-- 用户主表
CREATE TABLE IF NOT EXISTS users (
  id           BIGSERIAL PRIMARY KEY,
  uid          TEXT UNIQUE NOT NULL,            -- 外显ID（应用层生成）
  email        TEXT UNIQUE,                     -- 建议应用层统一转小写
  phone        TEXT UNIQUE,
  display_name TEXT,
  is_active    BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- 凭据表：支持 password / oauth / totp / webauthn
CREATE TABLE IF NOT EXISTS credentials (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type          TEXT   NOT NULL CHECK (type IN ('password','oauth','totp','webauthn')),
  secret_hash   TEXT,                            -- 密码哈希 / TOTP 秘钥 / WebAuthn 公钥等
  provider      TEXT,                            -- oauth: 'google'|'wechat'...
  provider_uid  TEXT,                            -- oauth 唯一 ID
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- 约束/索引：
-- 1) 每个用户最多一条指定类型的本地凭据（password/totp/webauthn）
CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_user_type_one
  ON credentials(user_id, type)
  WHERE type IN ('password','totp','webauthn');

-- 2) 第三方登录唯一性：同 provider + provider_uid 全局唯一
CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_oauth_unique
  ON credentials(provider, provider_uid)
  WHERE provider IS NOT NULL AND provider_uid IS NOT NULL;

-- 会话表（会话状态仍建议放 Redis；这里用于审计/吊销等）
CREATE TABLE IF NOT EXISTS sessions (
  id           BIGSERIAL PRIMARY KEY,
  session_id   TEXT UNIQUE NOT NULL,            -- 随机不可预测
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_agent   TEXT,
  ip           INET,
  expires_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT now(),
  revoked_at   TIMESTAMPTZ
);

-- 实用索引
CREATE INDEX IF NOT EXISTS idx_users_email_ci
  ON users((lower(email))) WHERE email IS NOT NULL;   -- 邮箱大小写不敏感的查找
CREATE INDEX IF NOT EXISTS idx_sessions_user
  ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires
  ON sessions(expires_at);

COMMIT;
