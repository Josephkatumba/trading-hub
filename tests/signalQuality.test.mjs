import test from "node:test";
import assert from "node:assert/strict";
import {POLICY_LABELS, calibrationTable, headline, policyTable, qualityPanel, statsTable, strategyStatusTable} from "../src/garden/signalQuality.mjs";

const s = (over = {}) => ({trades: 100, win_rate: 0.35, expectancy_r: -0.05, expectancy_ci95: [-0.1, 0.0], profit_factor: 0.9, total_r: -5, max_drawdown_r: 12, ...over});
const REPORT = {
  research: {
    target_instruments: {policies: {
      baseline: {selection_rate: 1, costs_1x: s(), costs_2x: s({expectancy_r: -0.12})},
      quality_A: {selection_rate: 0.064, costs_1x: s({trades: 20, expectancy_r: -0.004}), costs_2x: s({expectancy_r: -0.03})},
    }},
    random_control: {quality_A: {expectancy_r_mean: -0.056, expectancy_r_range: [-0.09, -0.01]}},
    grade_calibration: {target_instruments: {"A+": s({trades: 5}), REJECTED: s({expectancy_r: -0.15})}},
    breakdowns: {session: {baseline: {LONDON: s()}, quality_A: {LONDON: s({expectancy_r: 0.01})}}},
    strategy_status: {donchian: {baseline: s({avg_win_r: 1.9, avg_loss_r: -1.05}), quality_gated: s({trades: 30}), verdict: "IMPROVE (quality-gated, unproven)", reason: "positive only on A/A+ <setups>"}},
  },
  live_audit: {overall: {all: {resolved: 1632, win_rate: 0.3076, expectancy_r: -0.0756, total_r: -123.39}}, lifecycle: {setups: 10, confirm_rate: 0.03, expired_share: 0.87, invalidated_share: 0.1}},
  live_grading: {mode: "shadow", by_grade: {A: {signals: 2, resolved: 1, total_r: 2}}},
  notes: ["Live figures are hypothetical."],
};

test("policy table compares old and new engines including 2x costs", () => {
  const html = policyTable(REPORT.research.target_instruments);
  assert.match(html, new RegExp(POLICY_LABELS.baseline.replace(/[()]/g, ".")));
  assert.match(html, /New engine: A\/A\+ quality gate/);
  assert.match(html, /6\.4%/);
  assert.match(html, /-0\.120R/);
  assert.match(policyTable(null), /No walk-forward results/);
});

test("headline shows live record, both engines and the rejection rate", () => {
  const html = headline(REPORT);
  assert.match(html, /Live record/);
  assert.match(html, /Old engine · out of sample/);
  assert.match(html, /93\.6%/);
});

test("calibration keeps grade order and flags small samples; text is escaped", () => {
  const cal = calibrationTable(REPORT.research.grade_calibration.target_instruments);
  assert.ok(cal.indexOf("A+") < cal.indexOf("REJECTED"));
  assert.match(statsTable({X: s({sufficient: false})}), /small sample/);
  assert.match(strategyStatusTable(REPORT.research.strategy_status), /&lt;setups&gt;/);
});

test("panel renders every section and degrades when offline", () => {
  const html = qualityPanel(REPORT);
  for (const part of ["Random-selection control", "Session", "Live grading", "shadow", "Lifecycle: 10 setups"]) assert.ok(html.includes(part), part);
  assert.match(qualityPanel(null), /unavailable/);
  assert.match(qualityPanel({}), /No walk-forward results/);
});
