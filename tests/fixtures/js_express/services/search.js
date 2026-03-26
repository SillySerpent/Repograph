async function searchService(query, limit) {
    const rawResults = await runDbQuery(query, limit);
    return rankResults(rawResults);
}

async function runDbQuery(query, limit) {
    return [{ id: 1, text: `result for ${query}` }];
}

function rankResults(results) {
    return results.sort((a, b) => a.id - b.id);
}

module.exports = { searchService, runDbQuery, rankResults };
