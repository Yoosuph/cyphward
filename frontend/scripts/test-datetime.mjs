// Unit tests for src/lib/datetime.ts (clock changes, half-hour zones, round trips). Run: npm run test:datetime
import assert from "node:assert/strict";
import { transform } from "esbuild";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const source = await readFile(fileURLToPath(new URL("../src/lib/datetime.ts", import.meta.url)), "utf8");
const { code } = await transform(source, { loader: "ts", format: "esm" });
const dt = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
let passed = 0;
const test = (name, fn) => { fn(); passed += 1; console.log(`  ok  ${name}`); };

test("Lagos has no clock change: wall time minus one hour is UTC", () => {
  const r = dt.localToUtc("2026-10-15T09:30", "Africa/Lagos");
  assert.deepEqual([r.ok, r.utc], [true, "2026-10-15T08:30:00.000Z"]);
});
test("a time with seconds is accepted", () => {
  assert.equal(dt.localToUtc("2026-10-15T09:30:15", "Africa/Lagos").utc, "2026-10-15T08:30:15.000Z");
});
test("New York summer time is UTC-4, winter time UTC-5", () => {
  assert.equal(dt.localToUtc("2026-07-01T12:00", "America/New_York").utc, "2026-07-01T16:00:00.000Z");
  assert.equal(dt.localToUtc("2026-12-01T12:00", "America/New_York").utc, "2026-12-01T17:00:00.000Z");
});
test("a time the clocks skip is refused with a message, never guessed", () => {
  const r = dt.localToUtc("2026-03-08T02:30", "America/New_York");
  assert.equal(r.ok, false);
  assert.equal(r.reason, "nonexistent");
  assert.match(r.message, /does not exist/);
  assert.equal(r.utc, undefined);
});
test("a time that happens twice is refused with a message, never guessed", () => {
  const r = dt.localToUtc("2025-11-02T01:30", "America/New_York");
  assert.equal(r.ok, false);
  assert.equal(r.reason, "ambiguous");
  assert.match(r.message, /twice/);
});
test("times either side of a clock change are fine", () => {
  assert.equal(dt.localToUtc("2026-03-08T01:59", "America/New_York").utc, "2026-03-08T06:59:00.000Z");
  assert.equal(dt.localToUtc("2026-03-08T03:00", "America/New_York").utc, "2026-03-08T07:00:00.000Z");
  assert.equal(dt.localToUtc("2025-11-02T00:59", "America/New_York").utc, "2025-11-02T04:59:00.000Z");
  assert.equal(dt.localToUtc("2025-11-02T02:00", "America/New_York").utc, "2025-11-02T07:00:00.000Z");
});
test("Europe/London spring gap and autumn overlap", () => {
  assert.equal(dt.localToUtc("2026-03-29T01:30", "Europe/London").reason, "nonexistent");
  assert.equal(dt.localToUtc("2026-10-25T01:30", "Europe/London").reason, "ambiguous");
});
test("Lord Howe shifts by 30 minutes and is still handled", () => {
  assert.equal(dt.localToUtc("2026-10-04T02:15", "Australia/Lord_Howe").reason, "nonexistent");
  assert.equal(dt.localToUtc("2026-04-05T01:45", "Australia/Lord_Howe").reason, "ambiguous");
  assert.equal(dt.localToUtc("2026-07-01T12:00", "Australia/Lord_Howe").utc, "2026-07-01T01:30:00.000Z");
});
test("a half-hour zone without clock changes", () => {
  assert.equal(dt.localToUtc("2026-10-15T09:30", "Asia/Kolkata").utc, "2026-10-15T04:00:00.000Z");
});
test("invalid input is refused", () => {
  for (const bad of ["", "2026-13-01T10:00", "2026-02-30T10:00", "2026-10-15", "2026-10-15T25:00", "nonsense"]) {
    assert.equal(dt.localToUtc(bad, "Africa/Lagos").reason, "invalid", bad);
  }
});
test("an unknown zone falls back to Africa/Lagos", () => {
  assert.equal(dt.resolveZone("Mars/Olympus"), "Africa/Lagos");
  assert.equal(dt.localToUtc("2026-10-15T09:30", "Mars/Olympus").utc, "2026-10-15T08:30:00.000Z");
});
test("round trip: UTC to wall clock and back", () => {
  for (const zone of ["Africa/Lagos", "America/New_York", "Asia/Kolkata", "Australia/Lord_Howe", "Pacific/Chatham"]) {
    for (const iso of ["2026-01-15T10:20:00.000Z", "2026-07-15T22:05:00.000Z", "2026-10-15T00:00:00.000Z"]) {
      const wall = dt.utcToLocalInput(iso, zone);
      assert.equal(dt.localToUtc(wall, zone).utc, iso, `${zone} ${iso} via ${wall}`);
    }
  }
});
test("utcToLocalInput reads the zone, not the machine", () => {
  assert.equal(dt.utcToLocalInput("2026-10-15T23:30:00Z", "Africa/Lagos"), "2026-10-16T00:30");
  assert.equal(dt.utcToLocalInput("2026-10-15T23:30:00+01:00", "Africa/Lagos"), "2026-10-15T23:30");
  assert.equal(dt.utcToLocalInput(null, "Africa/Lagos"), "");
  assert.equal(dt.utcToLocalInput("not a date", "Africa/Lagos"), "");
});
test("today in the zone, across midnight", () => {
  assert.equal(dt.todayIn("Africa/Lagos", new Date("2026-10-15T23:30:00Z")), "2026-10-16");
  assert.equal(dt.todayIn("America/New_York", new Date("2026-10-15T23:30:00Z")), "2026-10-15");
});
test("addDays does calendar arithmetic", () => {
  assert.equal(dt.addDays("2026-02-27", 2), "2026-03-01");
  assert.equal(dt.addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(dt.addDays("2026-03-01", -1), "2026-02-28");
});
test("end of day is the last minute in the zone", () => {
  assert.equal(dt.endOfDayUtc("2026-10-15", "Africa/Lagos").utc, "2026-10-15T22:59:00.000Z");
  assert.equal(dt.endOfDayUtc("2026-07-01", "America/New_York").utc, "2026-07-02T03:59:00.000Z");
});
test("zone label shows the offset", () => {
  assert.equal(dt.zoneLabel("Africa/Lagos", new Date("2026-10-15T00:00:00Z")), "Africa/Lagos (UTC+01:00)");
  assert.equal(dt.zoneLabel("Asia/Kolkata", new Date("2026-10-15T00:00:00Z")), "Asia/Kolkata (UTC+05:30)");
});

console.log(`datetime: ${passed} tests passed`);
