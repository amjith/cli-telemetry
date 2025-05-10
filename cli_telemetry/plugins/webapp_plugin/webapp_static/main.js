// Utility: format duration (microseconds -> human-readable)
function formatDuration(us) {
    if (us >= 1e6) {
        return (us / 1e6).toFixed(2) + ' s';
    }
    if (us >= 1e3) {
        return (us / 1e3).toFixed(2) + ' ms';
    }
    return us + ' µs';
}
// On page load, fetch all users
document.addEventListener('DOMContentLoaded', () => {
    fetch('/api/users')
        .then(res => res.json())
        .then(data => renderUsersList(data))
        .catch(err => console.error(err));
});

function renderTracesList(traces) {
    const container = document.getElementById('tracesList');
    container.innerHTML = '';
    const ul = document.createElement('ul');
    traces.forEach(trace => {
        const li = document.createElement('li');
        const btn = document.createElement('button');
        btn.textContent = trace.trace_id;
        btn.addEventListener('click', () => loadTrace(trace.trace_id));
        li.appendChild(btn);
        const ts = new Date(trace.start_time / 1000);
        li.append(' (' + ts.toLocaleString() + ')');
        ul.appendChild(li);
    });
    container.appendChild(ul);
}

function loadTrace(traceId) {
    document.getElementById('spanTree').innerHTML = '';
    document.getElementById('attributesPane').textContent = '';
    fetch('/api/spans?trace_id=' + encodeURIComponent(traceId))
        .then(res => res.json())
        .then(data => renderSpanTree(data))
        .catch(err => console.error(err));
}

function renderSpanTree(spans) {
    const container = document.getElementById('spanTree');
    container.innerHTML = '';
    const ul = document.createElement('ul');
    spans.forEach(span => ul.appendChild(renderSpanNode(span)));
    container.appendChild(ul);
}

function renderSpanNode(span) {
    const li = document.createElement('li');
    const div = document.createElement('div');
    const durationUs = span.end_time - span.start_time;
    const durStr = formatDuration(durationUs);
    div.textContent = span.name + ' [' + durStr + ']';
    if (span.status_code === 1) div.classList.add('error');
    div.addEventListener('click', () => showAttributes(span));
    li.appendChild(div);
    if (span.children && span.children.length) {
        const ul = document.createElement('ul');
        span.children.forEach(child => ul.appendChild(renderSpanNode(child)));
        li.appendChild(ul);
    }
    return li;
}

function showAttributes(span) {
    const pane = document.getElementById('attributesPane');
    pane.textContent = JSON.stringify(span.attributes, null, 2);
}

function renderUsersList(users) {
    const container = document.getElementById('usersList');
    container.innerHTML = '';
    const ul = document.createElement('ul');
    users.forEach(user => {
        const li = document.createElement('li');
        const btn = document.createElement('button');
        btn.textContent = user;
        btn.addEventListener('click', () => loadTraces(user));
        li.appendChild(btn);
        ul.appendChild(li);
    });
    container.appendChild(ul);
}

function loadTraces(userId) {
    fetch('/api/traces?user_id=' + encodeURIComponent(userId))
        .then(res => res.json())
        .then(data => renderTracesList(data))
        .catch(err => console.error(err));
    document.getElementById('spanTree').innerHTML = '';
    document.getElementById('attributesPane').textContent = '';
}