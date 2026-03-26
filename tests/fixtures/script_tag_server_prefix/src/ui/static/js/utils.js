/* utils.js — utility functions callable as globals from app.js */
function apiFetch(url) {
    return fetch(url).then(function(r) { return r.json(); });
}

function formatPrice(p) {
    return p.toFixed(2);
}
