import {
  AUTH_COOKIE_NAME, type AuthContext, type AuthRequest, type AuthResponseWriter, type AuthSession,
} from '../dto/auth.types';

export function authContext(request: AuthRequest): AuthContext {
  let token = request.cookies?.[AUTH_COOKIE_NAME] ?? null;
  const header = request.headers?.cookie;
  if (!token && typeof header === 'string') {
    for (const part of header.split(';')) {
      const separator = part.indexOf('=');
      if (separator < 0 || part.slice(0, separator).trim() !== AUTH_COOKIE_NAME) continue;
      const value = part.slice(separator + 1).trim();
      try { token = decodeURIComponent(value); } catch { token = value; }
      break;
    }
  }
  return { token, ipAddress: (request.socket?.remoteAddress || request.ip || null)?.slice(0, 64) ?? null };
}

export function writeSession(response: AuthResponseWriter, session: AuthSession): void {
  const secure = /^(1|true|yes|on)$/i.test(process.env.AUTH_COOKIE_SECURE ?? 'false');
  response.cookie(AUTH_COOKIE_NAME, session.token, {
    maxAge: session.lifetimeSeconds * 1000, httpOnly: true, secure,
    sameSite: secure ? 'none' : 'lax', path: '/',
  });
}

export function clearSession(response: AuthResponseWriter): void {
  response.clearCookie(AUTH_COOKIE_NAME, { path: '/' });
}
