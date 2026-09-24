import test from "node:test";
import assert from "node:assert/strict";
import {inferSession, normalizeTradeTime, sessionForUtc, withTimeProvenance, UNVERIFIED_SESSION} from "../src/tradeTime.mjs";

test("London, New York and Tokyo-hours (Asia) trades classify from UTC", () => {
  assert.equal(inferSession("2026-09-16 09:15:00","UTC"),"London");
  assert.equal(inferSession("2026-09-16 14:38:32","UTC"),"New York");
  // Tokyo trading hours fall in the existing "Asia" bucket; the label is unchanged.
  assert.equal(inferSession("2026-09-16 02:00:00","UTC"),"Asia");
  assert.equal(inferSession("2026-09-16 10:00:00","Asia/Tokyo"),"Asia"); // 01:00 UTC
});

test("session boundaries are half-open [start, end) in UTC", () => {
  const at=t=>sessionForUtc("2026-09-16T"+t+"Z");
  assert.equal(at("07:59:59"),"Asia");
  assert.equal(at("08:00:00"),"London");
  assert.equal(at("12:59:59"),"London");
  assert.equal(at("13:00:00"),"New York");
  assert.equal(at("17:59:59"),"New York");
  assert.equal(at("18:00:00"),"Asia");
});

test("broker wall time is converted to UTC before classification (the audit bug)", () => {
  // 15:24 on a UTC+3 server clock (Athens, summer) is 12:24 UTC: London.
  const athens=normalizeTradeTime("2026-09-16 15:24:43","Europe/Athens");
  assert.equal(athens.status,"VERIFIED");
  assert.equal(athens.utc,"2026-09-16T12:24:43.000Z");
  assert.equal(inferSession("2026-09-16 15:24:43","Europe/Athens"),"London");
  // Read naively as UTC, 15:24 would have been classified as New York.
  assert.equal(inferSession("2026-09-16 15:24:43","UTC"),"New York");
  // A New York wall clock at 09:30 is 13:30 UTC -> New York (raw hour 9 would say London).
  assert.equal(inferSession("2026-09-16 09:30","America/New_York"),"New York");
});

test("MT5 dotted export format is parsed", () => {
  assert.equal(normalizeTradeTime("2026.09.16 14:38:32","UTC").utc,"2026-09-16T14:38:32.000Z");
});

test("DST: the same broker wall time maps to different UTC instants in winter and summer", () => {
  assert.equal(normalizeTradeTime("2026-01-15 15:30","Europe/Athens").utc,"2026-01-15T13:30:00.000Z");
  assert.equal(normalizeTradeTime("2026-07-15 15:30","Europe/Athens").utc,"2026-07-15T12:30:00.000Z");
  assert.equal(inferSession("2026-01-15 15:30","Europe/Athens"),"New York");
  assert.equal(inferSession("2026-07-15 15:30","Europe/Athens"),"London");
});

test("DST: nonexistent and ambiguous wall times are rejected, not guessed", () => {
  const gap=normalizeTradeTime("2026-03-29 01:30","Europe/London");
  assert.equal(gap.status,"INVALID");
  assert.equal(gap.reason,"NONEXISTENT_LOCAL_SOURCE_TIME");
  const overlap=normalizeTradeTime("2026-10-25 01:30","Europe/London");
  assert.equal(overlap.status,"UNVERIFIED");
  assert.equal(overlap.reason,"AMBIGUOUS_LOCAL_SOURCE_TIME");
  assert.equal(inferSession("2026-10-25 01:30","Europe/London"),UNVERIFIED_SESSION);
});

test("no basis, unknown basis or no time-of-day gives an explicit Unverified session", () => {
  assert.equal(normalizeTradeTime("2026-09-16 14:00",undefined).reason,"SOURCE_TIME_BASIS_UNVERIFIED");
  assert.equal(inferSession("2026-09-16 14:00",""),UNVERIFIED_SESSION);
  assert.equal(normalizeTradeTime("2026-09-16 14:00","Mars/Olympus").reason,"SOURCE_TIME_BASIS_UNKNOWN");
  assert.equal(normalizeTradeTime("2026-09-16","UTC").reason,"NO_TIME_OF_DAY");
  assert.equal(normalizeTradeTime("not a date","UTC").status,"INVALID");
  assert.equal(normalizeTradeTime("","UTC").status,"MISSING");
});

test("timestamps carrying an explicit offset are verified without a basis", () => {
  const n=normalizeTradeTime("2026-09-16T09:30:00-04:00");
  assert.equal(n.status,"VERIFIED");
  assert.equal(n.utc,"2026-09-16T13:30:00.000Z");
  assert.equal(normalizeTradeTime("2026-09-16T13:30:00Z").utc,"2026-09-16T13:30:00.000Z");
});

test("withTimeProvenance preserves raw data, keeps export sessions, and is idempotent", () => {
  const legacy={id:"MT5-1",time:"2026-09-16 12:58:34",session:"London"};
  const once=withTimeProvenance(legacy,"Europe/Athens");
  assert.equal(once.time,"2026-09-16 12:58:34");
  assert.equal(once.session,"London");             // 12:58 at UTC+3 = 09:58 UTC
  assert.equal(once.session_recorded,"London");
  assert.equal(once.time_basis,"Europe/Athens");
  const twice=withTimeProvenance(once,"Europe/Athens");
  assert.deepEqual(twice,once);
  const exported=withTimeProvenance({time:"2026-09-16 12:00",session:"Tokyo",session_source:"export"},"");
  assert.equal(exported.session,"Tokyo");
  const stamped=withTimeProvenance({time:"2026-09-16 09:30",source_timezone:"America/New_York"},"UTC");
  assert.equal(stamped.session,"New York");        // import-time basis wins over workspace default
  assert.equal(withTimeProvenance({time:"2026-09-16 09:30"},"").session,UNVERIFIED_SESSION);
});
