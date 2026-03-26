/* app.js — calls utils.js functions as globals (no import statement) */

function loadData(url) {
    apiFetch(url).then(function(data) {
        renderTable(data);
    });
}

function renderTable(data) {
    data.forEach(function(row) {
        var price = formatPrice(row.price);
        var ts = formatTs(row.timestamp);
        console.log(price, ts);
    });
}
