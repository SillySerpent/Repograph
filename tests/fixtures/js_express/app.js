const express = require('express');
const authRouter = require('./routes/auth');
const searchRouter = require('./routes/search');

const app = express();
app.use(express.json());
app.use('/auth', authRouter);
app.use('/search', searchRouter);

function startServer(port) {
    app.listen(port, () => {
        console.log(`Server running on port ${port}`);
    });
}

module.exports = { app, startServer };
