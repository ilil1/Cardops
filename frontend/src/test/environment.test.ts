import { describe, expect, it } from "vitest";

describe("프론트엔드 테스트 환경", () => {
  it("jsdom 문서 객체를 제공합니다", () => {
    expect(document).toBeDefined();
  });
});
