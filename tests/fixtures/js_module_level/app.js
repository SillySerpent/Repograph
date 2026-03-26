/** Fixture: top-level call must reach callee via __module__ sentinel (JS parity). */
function liveCallee() {
  return 42;
}

function neverCalled() {
  return 0;
}

liveCallee();
