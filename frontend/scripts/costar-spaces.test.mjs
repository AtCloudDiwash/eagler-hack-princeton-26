import assert from "node:assert/strict";
import test from "node:test";
import { leasingRows } from "../lib/costar-spaces.ts";

const range = { min_sqft: 1620, max_sqft: 2530 };
const space = (suite, sqft, extra = {}) => ({ listing_id: 1, suite, floor: "First Floor", sqft, sqft_min: sqft, sqft_max: sqft, rent_per_sqft_yr: 30, service: "TripleNet", use: "Office", lease_pending: false, available_on: null, ...extra });

test("the selected Suite 3445 precedes smaller fitting alternatives", () => {
  const selected = space("3445", 2180);
  const rows = leasingRows([space("T-06", 1768), selected, space("140", 2297)], selected, range);
  assert.equal(rows[0].space.suite, "3445");
  assert.equal(rows[0].space.sqft, 2180);
  assert.deepEqual(rows.map(r => r.selected), [true, false, false]);
});

test("a selected suite remains visible if an older response omitted it", () => {
  const selected = space("3445", 2180);
  const rows = leasingRows([space("T-06", 1768)], selected, range);
  assert.equal(rows[0].space.suite, "3445");
  assert.equal(rows.length, 2);
});

test("suite names alone do not identify a selection", () => {
  const selected = space("3445", 2180, { listing_id: 2, floor: "Thirty Fourth Floor" });
  const rows = leasingRows([space("3445", 2180), space("3445", 2180, { listing_id: 2 }), selected], selected, range);
  assert.equal(rows.filter(r => r.selected).length, 1);
  assert.deepEqual(rows[0].space, selected);
  assert.equal(rows.length, 3);
});

test("a proposed portion uses the selected area and preserves its advertised bounds", () => {
  const advertised = space("100", 10000, { sqft_min: 500 });
  const selected = { ...advertised, sqft: 2000, suggested_portion: true };
  const rows = leasingRows([advertised], selected, range);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].space.sqft, 2000);
  assert.equal(rows[0].space.sqft_max, 10000);
  assert.equal(rows[0].space.suggested_portion, true);
  assert.equal(rows[0].fits, true);
});

test("divisible alternatives fit by their advertised range and pending leases do not", () => {
  const rows = leasingRows([
    space("pending", 2000, { lease_pending: true }),
    space("divisible", 10000, { sqft_min: 500 }),
  ], null, range);
  assert.equal(rows[0].space.suite, "divisible");
  assert.equal(rows[0].fits, true);
  assert.equal(rows[1].fits, false);
  assert.ok(rows.every(r => !r.selected));
});
