import test from "node:test";
import assert from "node:assert/strict";
import { validateApiOrigin } from "../scripts/build-pages.mjs";

test("accepts hosted HTTPS origins with an optional trailing slash", () => {
  assert.doesNotThrow(() => validateApiOrigin("https://api.example.test"));
  assert.doesNotThrow(() => validateApiOrigin("https://api.example.test/"));
});

for (const value of [
  undefined,
  "",
  "http://api.example.test",
  "https://localhost",
  "https://dev.localhost",
  "https://127.0.0.1",
  "https://127.1.2.3",
  "https://[::1]",
  "https://0.0.0.0",
  "https://user:secret@api.example.test",
  "https://api.example.test/path",
  "https://api.example.test?key=secret",
  "https://api.example.test#fragment",
  "https://api.example.test:bad",
  "not a url",
  " https://api.example.test",
  "https://api.example.test ",
]) {
  test(`rejects invalid target ${String(value).length}`, () => {
    assert.throws(
      () => validateApiOrigin(value),
      /non-loopback HTTPS origin/,
    );
  });
}
