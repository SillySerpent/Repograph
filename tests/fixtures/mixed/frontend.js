async function sendRequest(data) {
    const payload = buildPayload(data);
    const response = await fetch('/api/process', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    return handleResponse(response);
}

function buildPayload(data) {
    return { data: data, timestamp: Date.now() };
}

async function handleResponse(response) {
    const json = await response.json();
    if (!json.status) {
        throw new Error('Bad response');
    }
    return json.result;
}
