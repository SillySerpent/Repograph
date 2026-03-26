/* app.js — calls utils.js functions as globals */
function loadData(url) {
    apiFetch(url).then(function(data) {
        var p = formatPrice(data.price);
        console.log(p);
    });
}
