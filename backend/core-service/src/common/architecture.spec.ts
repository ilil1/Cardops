import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : path.endsWith('.ts') && !path.endsWith('.spec.ts') ? [path] : [];
  });
}

describe('layer boundaries', () => {
  const sources = files(resolve(__dirname, '..'));
  it('controllers do not access repositories, database drivers, or AI infrastructure directly', () => {
    for (const file of sources.filter(path => path.endsWith('.controller.ts'))) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/from ['"][^'"]*(?:repositories|infrastructure|mysql2)/);
    }
  });
  it('application services contain no SQL or HTTP cookie handling', () => {
    for (const file of sources.filter(path => path.includes('/services/') || path.endsWith('/system.service.ts'))) {
      const source = readFileSync(file, 'utf8');
      expect(source, file).not.toMatch(/\b(?:SELECT\s|INSERT INTO|UPDATE \w+ SET|DELETE FROM)/);
      expect(source, file).not.toMatch(/\.cookie\(|\.clearCookie\(|AuthResponseWriter|AuthRequest/);
      expect(source, file).not.toMatch(/import \{[^}]*\bDatabaseService\b/);
    }
  });
  it('repositories never depend on controllers or application services', () => {
    for (const file of sources.filter(path => path.includes('/repositories/'))) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/from ['"][^'"]*(?:controllers|services)\//);
    }
  });
});
