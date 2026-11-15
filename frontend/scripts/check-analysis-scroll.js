/* Run this expression in the browser evaluator on a completed /analysis/<id> dashboard.
 * Regression: changing the sticky score bar's height caused ~50 px jumps near the hero boundary.
 * This intentionally needs a real browser with scroll anchoring, not a DOM mock.
 */
(async () => {
  if (!document.querySelector('header') || !document.querySelector('main section')) {
    throw new Error('Open a completed analysis dashboard before running this check.');
  }
  const originalY = window.scrollY;
  const jumps = [];
  for (const y of [0, 400, 420, 440, 460, 480, 500, 520, 540, 560, 540, 520, 500, 480, 460, 440, 420, 400]) {
    window.scrollTo(0, y);
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    if (Math.abs(window.scrollY - y) > 5) jumps.push({ requested: y, actual: window.scrollY });
  }
  window.scrollTo(0, originalY);
  if (jumps.length) throw new Error(`Scroll jumped at the header boundary: ${JSON.stringify(jumps)}`);
  return { pass: true, checkedPositions: 18 };
})();
