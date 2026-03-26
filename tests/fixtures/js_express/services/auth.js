const crypto = require('crypto');

async function validateCredentials(email, password) {
    const user = await findUserByEmail(email);
    if (!user) return null;
    if (checkPasswordHash(user.passwordHash, password)) {
        return user;
    }
    return null;
}

async function findUserByEmail(email) {
    if (email === 'test@example.com') {
        return { id: 1, email, passwordHash: 'hashed_secret' };
    }
    return null;
}

function checkPasswordHash(storedHash, password) {
    return storedHash === 'hashed_' + password;
}

function generateToken(user) {
    return 'token_' + user.id;
}

module.exports = { validateCredentials, generateToken, findUserByEmail };
