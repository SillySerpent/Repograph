const express = require('express');
const { validateCredentials, generateToken } = require('../services/auth');

const router = express.Router();

async function loginHandler(req, res) {
    const { email, password } = req.body;
    const user = await validateCredentials(email, password);
    if (!user) {
        return res.status(401).json({ error: 'Invalid credentials' });
    }
    const token = generateToken(user);
    return res.json({ token });
}

async function logoutHandler(req, res) {
    return res.json({ status: 'ok' });
}

router.post('/login', loginHandler);
router.post('/logout', logoutHandler);

module.exports = router;
