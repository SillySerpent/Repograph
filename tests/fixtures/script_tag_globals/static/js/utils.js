/* utils.js — Shared formatting helpers loaded via script tag (global scope) */

function formatPrice(price) {
    return price.toFixed(2);
}

function formatTs(ts) {
    return new Date(ts).toISOString();
}

function apiFetch(url) {
    return fetch(url).then(r => r.json());
}

/* Helper only called from within this file — also a script global */
function _internal_helper(x) {
    return x * 2;
}
