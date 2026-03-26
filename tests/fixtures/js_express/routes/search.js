const express = require('express');
const { searchService } = require('../services/search');

const router = express.Router();

async function searchEndpoint(req, res) {
    const { query, limit = 10 } = req.query;
    const results = await searchService(query, limit);
    return res.json({ results, count: results.length });
}

router.get('/', searchEndpoint);

module.exports = router;
