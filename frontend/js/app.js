/*
Frontend JavaScript Controller (frontend/js/app.js)

PURPOSE:
Manages client-side interaction, including tab switching, browser-based audio recording, 
API uploads, interactive form populations, validation, and real-time console tracing.

FLOW:
1. On load, fetches accounts and drafts from the backend.
2. Dynamically builds the dashboard metrics and table rows.
3. Handles microphone capture via the Web Audio MediaRecorder API.
4. Posts audio/text payloads to FastAPI backend endpoints.
5. Auto-populates extracted payment form values.
6. Synchronizes state and triggers re-validation (checks balance, category, names).
7. Shows agent pipeline traces in the log console.
*/

// Base API URL configuration (relative path since server hosts UI)
const API_BASE = window.location.origin;

// Application State
let accounts = [];
let drafts = [];
let currentDraft = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

// Sample training prompts for students to click and test
const SAMPLE_PROMPTS = [
    "Pay ABC Suppliers five thousand rupees tomorrow from my current account.",
    "Transfer ten thousand to ABC Suppliers.",
    "Transfer five hundred dollars from my USD account to Global Logistics Corp.",
    "Send 300 euros to Tech Solutions Germany on next Monday.",
    "Pay 150 rupees from savings to Charlie Local Groceries"
];

// Initialize on window load
window.addEventListener('DOMContentLoaded', () => {
    initApp();
});

async function initApp() {
    setupSampleUtterances();
    await loadAccounts();
    await loadDrafts();
}

// ----------------------------------------------------
// UI TABS SWITCHING
// ----------------------------------------------------
function switchTab(tabId) {
    // 1. Deactivate all tabs
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    // 2. Find and activate clicked tab
    const tabIndex = ['dashboard', 'voice', 'form', 'review'].indexOf(tabId);
    if (tabIndex !== -1) {
        document.querySelectorAll('.tab-btn')[tabIndex].classList.add('active');
        document.getElementById(tabId).classList.add('active');
    }
}

// ----------------------------------------------------
// DATA FETCHING & SYNC
// ----------------------------------------------------
async function loadAccounts() {
    try {
        const response = await fetch(`${API_BASE}/api/accounts`);
        if (!response.ok) throw new Error("Failed to load accounts.");
        accounts = await response.json();

        // Populate form dropdown selects
        populateAccountSelects();
        // Update dashboard balances
        updateDashboardBalances();
    } catch (err) {
        console.error("Error loading accounts:", err);
    }
}

async function loadDrafts() {
    try {
        const response = await fetch(`${API_BASE}/api/drafts`);
        if (!response.ok) throw new Error("Failed to load drafts.");
        drafts = await response.json();

        // Update metrics & table
        updateDraftsTable();
    } catch (err) {
        console.error("Error loading drafts:", err);
    }
}

function updateDashboardBalances() {
    // San Shy Current: 11223344
    const current = accounts.find(a => a.account_number === '11223344');
    // San Shy Savings: 55667788
    const savings = accounts.find(a => a.account_number === '55667788');

    if (current) {
        document.getElementById('user-current-balance').innerText = `${current.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })} ${current.currency}`;
    }
    if (savings) {
        document.getElementById('user-savings-balance').innerText = `${savings.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })} ${savings.currency}`;
    }
}

function populateAccountSelects() {
    const debtorSelect = document.getElementById('form-debtor');
    const creditorSelect = document.getElementById('form-creditor');

    // Clear elements
    debtorSelect.innerHTML = '<option value="">-- Select Debtor (Sender) --</option>';
    creditorSelect.innerHTML = '<option value="">-- Select Creditor (Receiver) --</option>';

    accounts.forEach(acc => {
        const optionText = `${acc.account_holder} (${acc.account_number}) - Bal: ${acc.balance} ${acc.currency}`;

        const optDebtor = new Option(optionText, acc.account_number);
        const optCreditor = new Option(optionText, acc.account_number);

        debtorSelect.add(optDebtor);
        creditorSelect.add(optCreditor);
    });
}

function updateDraftsTable() {
    const tbody = document.getElementById('drafts-table-body');
    const draftsCount = document.getElementById('drafts-count');

    draftsCount.innerText = drafts.length;

    if (drafts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary);">No drafts available. Run a voice command to create one.</td></tr>`;
        return;
    }

    tbody.innerHTML = '';
    drafts.forEach(d => {
        // Find debtor and creditor names
        const debtorObj = accounts.find(a => a.account_number === d.debtor_account);
        const creditorObj = accounts.find(a => a.account_number === d.creditor_account);

        const debtorName = debtorObj ? debtorObj.account_holder.split(" ")[0] + "..." : (d.debtor_account || "N/A");
        const creditorName = creditorObj ? creditorObj.account_holder : (d.creditor_account || "N/A");

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>#${d.id}</td>
            <td title="${d.debtor_account}">${debtorName}</td>
            <td title="${d.creditor_account}">${creditorName}</td>
            <td style="font-weight: 600; color: #FFF;">${d.amount ? d.amount.toLocaleString() : '0'} ${d.currency}</td>
            <td>${d.payment_date || 'N/A'}</td>
            <td><span class="badge-tag" style="font-size:0.75rem; background:rgba(99,102,241,0.1); border-color:var(--border-color); color:#A5B4FC;">${d.category || 'Domestic'}</span></td>
            <td><span class="badge-status ${d.status.toLowerCase()}">${d.status}</span></td>
            <td>
                <button class="btn btn-primary" style="padding: 0.4rem 0.8rem; font-size: 0.75rem;" onclick="loadDraftForExecution(${d.id})">
                    ${d.status === 'Draft' ? 'Review & Pay' : 'View'}
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// ----------------------------------------------------
// CORE AUDIO RECORDING & PLAYBACK
// ----------------------------------------------------
async function toggleRecording() {
    const recordBtn = document.getElementById('record-btn');
    const recordStatus = document.getElementById('record-status');
    const playbackContainer = document.getElementById('audio-playback-container');

    if (isRecording) {
        // Stop recording
        mediaRecorder.stop();
        isRecording = false;
        recordBtn.classList.remove('recording');
        recordStatus.innerText = "Processing recorded audio...";
    } else {
        // Start recording
        audioChunks = [];
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

                // Show playback element
                const audioURL = URL.createObjectURL(audioBlob);
                const audioElem = document.getElementById('recorded-audio');
                audioElem.src = audioURL;
                playbackContainer.style.display = 'block';

                // Upload recorded blob to API
                await uploadAudioBlob(audioBlob, "recorded_mic.webm");
            };

            mediaRecorder.start();
            isRecording = true;
            recordBtn.classList.add('recording');
            recordStatus.innerText = "Recording active... click to stop.";
            playbackContainer.style.display = 'none';
        } catch (err) {
            console.error("Microphone access blocked:", err);
            recordStatus.innerText = "Microphone access error. Please use manual files upload or click test prompts.";
            alert("Could not access microphone. Ensure permissions are granted or use Option B (Upload File).");
        }
    }
}

// ----------------------------------------------------
// FILE UPLOAD AND PARSING API INTERFACES
// ----------------------------------------------------
async function handleAudioUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadStatus = document.getElementById('upload-status');
    uploadStatus.innerText = `Uploading '${file.name}'...`;

    await uploadAudioBlob(file, file.name);
}

async function uploadAudioBlob(blob, filename) {
    const formData = new FormData();
    formData.append("file", blob, filename);

    try {
        const response = await fetch(`${API_BASE}/api/transcribe`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Transcription API error.");
        }

        const state = await response.json();
        handleOrchestratorResult(state);

        const uploadStatus = document.getElementById('upload-status');
        if (uploadStatus) uploadStatus.innerText = "Upload completed and parsed!";

        const recordStatus = document.getElementById('record-status');
        if (recordStatus) recordStatus.innerText = "Audio parsed successfully.";

    } catch (err) {
        console.error("Upload failed:", err);
        alert(`Failed to process audio: ${err.message}`);
        const uploadStatus = document.getElementById('upload-status');
        if (uploadStatus) uploadStatus.innerText = "Error: " + err.message;
    }
}

function setupSampleUtterances() {
    const container = document.getElementById('sample-utterances');
    container.innerHTML = '';

    SAMPLE_PROMPTS.forEach(prompt => {
        const pill = document.createElement('button');
        pill.className = 'utterance-pill';
        pill.innerText = `"${prompt}"`;
        pill.onclick = () => {
            document.getElementById('manual-text-input').value = prompt;
            processManualText(prompt);
        };
        container.appendChild(pill);
    });
}

async function processManualText(directText = null) {
    const text = directText || document.getElementById('manual-text-input').value.trim();
    if (!text) {
        alert("Please enter or select a payment command.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/process-text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });

        if (!response.ok) throw new Error("Parsing API error.");

        const state = await response.json();
        handleOrchestratorResult(state);
    } catch (err) {
        console.error("Text parsing failed:", err);
        alert(err.message);
    }
}

// ----------------------------------------------------
// PIPELINE RESPONSE HANDLER
// ----------------------------------------------------
function handleOrchestratorResult(state) {
    console.log("AI Pipeline State:", state);

    // 1. Update Speech Transcript Screen 2
    const transcriptBox = document.getElementById('speech-transcript');
    transcriptBox.innerText = state.raw_text;
    transcriptBox.classList.remove('empty');

    // 2. Display extracted entities
    const entitiesBox = document.getElementById('extracted-entities');
    entitiesBox.innerHTML = '';

    const ents = state.extracted_entities;
    if (Object.keys(ents).length === 0 || (!ents.debtor && !ents.creditor && !ents.amount)) {
        entitiesBox.innerHTML = '<div style="color: var(--text-secondary); font-style: italic;">No entities extracted.</div>';
    } else {
        const tags = [
            { label: 'Amount', value: ents.amount ? `${ents.amount} ${ents.currency}` : null },
            { label: 'Date', value: ents.payment_date },
            { label: 'Creditor (Key)', value: ents.creditor },
            { label: 'Debtor (Key)', value: ents.debtor }
        ];

        const tagsContainer = document.createElement('div');
        tagsContainer.className = 'entity-tags-container';

        tags.forEach(t => {
            if (t.value) {
                tagsContainer.innerHTML += `
                    <div class="entity-tag">
                        <span class="label">${t.label}:</span>
                        <span>${t.value}</span>
                    </div>
                `;
            }
        });
        entitiesBox.appendChild(tagsContainer);
    }

    // 3. Populate Form (Screen 3)
    document.getElementById('form-draft-id').value = ''; // Reset draft ID for new voice inputs
    document.getElementById('form-amount').value = state.amount || '';
    document.getElementById('form-currency').value = state.currency || 'INR';
    document.getElementById('form-date').value = state.payment_date || '';
    document.getElementById('form-notes').value = state.raw_text ? `Voice Entry: "${state.raw_text}"` : '';

    if (state.debtor_account) {
        document.getElementById('form-debtor').value = state.debtor_account.account_number;
    } else {
        document.getElementById('form-debtor').value = '';
    }

    if (state.creditor_account) {
        document.getElementById('form-creditor').value = state.creditor_account.account_number;
    } else {
        document.getElementById('form-creditor').value = '';
    }

    // Auto calculate category based on loaded dropdowns
    document.getElementById('form-category').value = state.category || 'Domestic Payment';

    // Enable form access
    document.getElementById('next-to-form-btn').disabled = false;

    // Update Review View logs console (Screen 4)
    updateLogsConsole(state.execution_logs);

    // Store current state mock draft object
    currentDraft = {
        debtor_account: state.debtor_account ? state.debtor_account.account_number : '',
        creditor_account: state.creditor_account ? state.creditor_account.account_number : '',
        amount: state.amount || 0,
        currency: state.currency || 'INR',
        payment_date: state.payment_date || '',
        category: state.category || 'Domestic Payment',
        notes: state.raw_text || '',
        status: 'Draft'
    };

    // Switch validation screen outputs
    updateReviewScreen(state);

    // Visual alert to user
    alert("Voice parsed! Review fields in 'Payment Form' or 'Review & Execute' tabs.");
}

function updateLogsConsole(logs) {
    const consoleBox = document.getElementById('agent-logs-console');
    if (!logs || logs.length === 0) {
        consoleBox.innerText = "[System Log] Clear.";
        return;
    }

    consoleBox.innerHTML = '';
    logs.forEach(log => {
        consoleBox.innerHTML += `<div>&gt; ${log}</div>`;
    });
    // Scroll to bottom
    consoleBox.scrollTop = consoleBox.scrollHeight;
}

// ----------------------------------------------------
// PAYMENT ENTRY FORM CONTROLS
// ----------------------------------------------------
function resetPaymentForm() {
    document.getElementById('payment-form').reset();
    document.getElementById('form-draft-id').value = '';
    currentDraft = null;

    // Disable form button
    document.getElementById('next-to-form-btn').disabled = true;

    // Reset review cards
    document.getElementById('validation-cards-container').innerHTML = `
        <div style="color: var(--text-secondary); font-style: italic; text-align: center; padding: 2rem 0;">
            No transaction loaded. Fill the form or run a voice prompt to initiate validation.
        </div>
    `;
    document.getElementById('tx-summary-card').style.display = 'none';
}

function triggerRevalidation() {
    // Reads form state, runs local calculations, and updates the review screen
    const debtorNum = document.getElementById('form-debtor').value;
    const creditorNum = document.getElementById('form-creditor').value;
    const amount = parseFloat(document.getElementById('form-amount').value) || 0;
    const currency = document.getElementById('form-currency').value;

    if (!debtorNum || !creditorNum || !amount) return;

    const debtorObj = accounts.find(a => a.account_number === debtorNum);
    const creditorObj = accounts.find(a => a.account_number === creditorNum);

    // 1. Calculate category type dynamically
    let category = "Domestic Payment";
    if (debtorObj && creditorObj) {
        if (currency !== debtorObj.currency || currency !== creditorObj.currency) {
            category = "Multi-Currency Payment";
        } else if (debtorObj.country !== creditorObj.country) {
            category = "International Payment";
        }
    }
    document.getElementById('form-category').value = category;

    // 2. Form mock state for review
    const mockState = {
        debtor_account: debtorObj,
        creditor_account: creditorObj,
        amount: amount,
        currency: currency,
        payment_date: document.getElementById('form-date').value,
        category: category,
        raw_text: document.getElementById('form-notes').value,
        validation_results: {
            is_valid: true,
            errors: [],
            warnings: [],
            balance_checked: true,
            sufficient_funds: true
        },
        execution_logs: [
            "Local Validation Agent: Active.",
            `Debtor: ${debtorObj ? debtorObj.account_holder : 'N/A'}`,
            `Creditor: ${creditorObj ? creditorObj.account_holder : 'N/A'}`,
            `Amount: ${amount} ${currency}`,
            `Classification: ${category}`
        ]
    };

    // Run funds verification
    if (debtorObj) {
        if (debtorObj.balance < amount) {
            mockState.validation_results.sufficient_funds = false;
            mockState.validation_results.is_valid = false;
            mockState.validation_results.errors.push(`Insufficient funds. Sender has ${debtorObj.balance} ${debtorObj.currency}. Required: ${amount} ${currency}.`);
        }
    }

    updateReviewScreen(mockState);
}

async function saveFormDraft() {
    const debtorNum = document.getElementById('form-debtor').value;
    const creditorNum = document.getElementById('form-creditor').value;
    const amount = parseFloat(document.getElementById('form-amount').value);
    const currency = document.getElementById('form-currency').value;
    const date = document.getElementById('form-date').value;
    const category = document.getElementById('form-category').value;
    const notes = document.getElementById('form-notes').value;
    const draftIdStr = document.getElementById('form-draft-id').value;

    if (!debtorNum || !creditorNum || isNaN(amount) || amount <= 0 || !date) {
        alert("Please fill out all mandatory fields (*) with valid details.");
        return;
    }

    const draftPayload = {
        debtor_account: debtorNum,
        creditor_account: creditorNum,
        amount: amount,
        currency: currency,
        payment_date: date,
        category: category,
        notes: notes,
        status: 'Draft'
    };

    if (draftIdStr) {
        draftPayload.id = parseInt(draftIdStr);
    }

    try {
        const response = await fetch(`${API_BASE}/api/drafts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draftPayload)
        });

        if (!response.ok) throw new Error("Failed to save draft.");

        const result = await response.json();
        alert("Draft successfully saved! Navigating to Review...");

        // Reload list and update
        await loadDrafts();

        // Store current draft reference
        currentDraft = result.draft;
        document.getElementById('form-draft-id').value = result.draft.id;

        // Populate review summary values
        triggerRevalidation();

        // Switch to Review
        switchTab('review');
    } catch (err) {
        console.error("Save draft error:", err);
        alert(err.message);
    }
}

// ----------------------------------------------------
// PAYMENT REVIEW & EXECUTION PROCEDURES
// ----------------------------------------------------
function updateReviewScreen(state) {
    const container = document.getElementById('validation-cards-container');
    const summaryCard = document.getElementById('tx-summary-card');

    // Clear old checks
    container.innerHTML = '';

    const val = state.validation_results;
    const debtor = state.debtor_account;
    const creditor = state.creditor_account;
    const amount = state.amount;
    const currency = state.currency;

    // Set execution button state
    const executeBtn = document.getElementById('execute-payment-btn');
    executeBtn.disabled = !val.is_valid;

    // 1. Render Sender Account Check Card
    if (debtor) {
        container.innerHTML += `
            <div class="validation-card">
                <div class="validation-icon success">
                    <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                </div>
                <div class="validation-details">
                    <h4>Debtor Account Verified</h4>
                    <p>Account holder "${debtor.account_holder}" exists. Country: ${debtor.country}.</p>
                </div>
            </div>
        `;
    } else {
        container.innerHTML += `
            <div class="validation-card invalid">
                <div class="validation-icon error">
                    <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                </div>
                <div class="validation-details">
                    <h4>Invalid Sender Account</h4>
                    <p>No valid source account identified. Please update manually in form.</p>
                </div>
            </div>
        `;
    }

    // 2. Render Recipient Account Check Card
    if (creditor) {
        container.innerHTML += `
            <div class="validation-card">
                <div class="validation-icon success">
                    <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                </div>
                <div class="validation-details">
                    <h4>Creditor Account Verified</h4>
                    <p>Account holder "${creditor.account_holder}" exists. Country: ${creditor.country}.</p>
                </div>
            </div>
        `;
    } else {
        container.innerHTML += `
            <div class="validation-card invalid">
                <div class="validation-icon error">
                    <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                </div>
                <div class="validation-details">
                    <h4>Missing Recipient Account</h4>
                    <p>Target vendor/person could not be matched. Specify a valid creditor in form.</p>
                </div>
            </div>
        `;
    }

    // 3. Render Balance Sufficiency Check Card
    if (debtor && amount) {
        if (val.sufficient_funds) {
            container.innerHTML += `
                <div class="validation-card">
                    <div class="validation-icon success">
                        <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                    </div>
                    <div class="validation-details">
                        <h4>Funds Available (Balance Verified)</h4>
                        <p>Available balance (${debtor.balance.toLocaleString()} ${debtor.currency}) exceeds payment amount (${amount.toLocaleString()} ${currency}).</p>
                    </div>
                </div>
            `;
        } else {
            container.innerHTML += `
                <div class="validation-card invalid">
                    <div class="validation-icon error">
                        <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                    </div>
                    <div class="validation-details">
                        <h4>Insufficient Funds Detected</h4>
                        <p>Sender account balance (${debtor.balance.toLocaleString()} ${debtor.currency}) is insufficient to execute payment of ${amount.toLocaleString()} ${currency}.</p>
                    </div>
                </div>
            `;
        }
    }

    // 4. Render Warnings list card if warnings exist
    if (val.warnings && val.warnings.length > 0) {
        let warningItemsHTML = '';
        val.warnings.forEach(w => warningItemsHTML += `<li>${w}</li>`);

        container.innerHTML += `
            <div class="validation-card warning">
                <div class="validation-icon warning">
                    <svg width="24" height="24" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                </div>
                <div class="validation-details">
                    <h4>Security / Regulatory Warnings</h4>
                    <ul class="validation-list">
                        ${warningItemsHTML}
                    </ul>
                </div>
            </div>
        `;
    }

    // Update Transfer Summary Card Details
    if (debtor && creditor && amount) {
        document.getElementById('summary-debtor-name').innerText = debtor.account_holder;
        document.getElementById('summary-debtor-num').innerText = `Acct: ${debtor.account_number} (${debtor.account_type})`;
        document.getElementById('summary-debtor-bal').innerText = `Balance: ${debtor.balance.toLocaleString()} ${debtor.currency}`;

        document.getElementById('summary-creditor-name').innerText = creditor.account_holder;
        document.getElementById('summary-creditor-num').innerText = `Acct: ${creditor.account_number} (${creditor.account_type})`;
        document.getElementById('summary-creditor-bal').innerText = `Country: ${creditor.country}`;

        document.getElementById('summary-tx-amount').innerText = `${amount.toLocaleString()} ${currency}`;

        let displayCat = state.category;
        if (state.purpose) {
            displayCat += ` (${state.purpose})`;
        }
        document.getElementById('summary-tx-category').innerText = displayCat;

        summaryCard.style.display = 'block';
    } else {
        summaryCard.style.display = 'none';
    }

    // Sync trace logs
    if (state.execution_logs) {
        updateLogsConsole(state.execution_logs);
    }
}

async function loadDraftForExecution(draftId) {
    const draft = drafts.find(d => d.id === draftId);
    if (!draft) return;

    currentDraft = draft;

    // 1. Populate form fields
    document.getElementById('form-draft-id').value = draft.id;
    document.getElementById('form-debtor').value = draft.debtor_account || '';
    document.getElementById('form-creditor').value = draft.creditor_account || '';
    document.getElementById('form-amount').value = draft.amount || '';
    document.getElementById('form-currency').value = draft.currency || 'INR';
    document.getElementById('form-date').value = draft.payment_date || '';
    document.getElementById('form-notes').value = draft.notes || '';
    document.getElementById('form-category').value = draft.category || 'Domestic Payment';

    // Enable form tab button
    document.getElementById('next-to-form-btn').disabled = false;

    // Trigger validation and loading
    triggerRevalidation();

    if (draft.status === 'Submitted') {
        // Block submit button if already completed
        setTimeout(() => {
            document.getElementById('execute-payment-btn').disabled = true;
            document.getElementById('execute-payment-btn').innerText = "Already Processed";
        }, 100);
    } else {
        setTimeout(() => {
            document.getElementById('execute-payment-btn').innerText = "Confirm & Execute Payment";
        }, 100);
    }

    // Nav to review
    switchTab('review');
}

async function submitPaymentTransaction() {
    if (!currentDraft || !currentDraft.id) {
        alert("Please save the payment draft first before confirming.");
        return;
    }

    const confirmSubmit = confirm("Are you sure you want to execute this bank payment and transfer funds?");
    if (!confirmSubmit) return;

    try {
        const response = await fetch(`${API_BASE}/api/submit-payment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ draft_id: currentDraft.id })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Payment submission failed.");
        }

        alert("Payment completed successfully! Sender and recipient balances updated.");

        // Reset state
        resetPaymentForm();

        // Reload all data
        await initApp();

        // Switch to dashboard
        switchTab('dashboard');

    } catch (err) {
        console.error("Submission failed:", err);
        alert(`Payment error: ${err.message}`);
    }
}

function clearVoiceInput() {
    document.getElementById('speech-transcript').innerText = "No audio processed yet. Speak, upload, or click a course test prompt above.";
    document.getElementById('speech-transcript').classList.add('empty');
    document.getElementById('extracted-entities').innerHTML = '<div style="color: var(--text-secondary); font-style: italic;">No entities extracted yet.</div>';
    document.getElementById('next-to-form-btn').disabled = true;
    currentDraft = null;
}
