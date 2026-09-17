// DOM Elements
let currentUser = window.currentUsername || getCookie('username') || document.querySelector('.user-info h3')?.textContent || 'admin';
let currentPage = 'dashboard';
let audioContext = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let selectedFile = null;
let recordedAudio = null;
let recordingTimer = null;
let recordingStartTime = null;
let stressChart = null;
let timelineChart = null;

// Helper function to get cookie value
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Update current time
    updateCurrentTime();
    setInterval(updateCurrentTime, 1000);
    
    // Setup navigation
    setupNavigation();
    
    // Load dashboard data
    if (currentPage === 'dashboard') {
        // Initialize charts FIRST before loading data
        initializeCharts();
        loadDashboardData();
        loadRecentEvents();
    }
    
    // Note: Audio upload and wound detection event listeners are set up inline in index.html
    // to avoid duplicate listeners. Do not set them up here.

    // Setup recording
    setupRecording();
    
    // Setup wound detection
    initializeWoundDetection();
    
    // Setup history
    loadHistory();
    
    // Load settings
    loadSettings();
    
    // Setup event listeners
    document.getElementById('alert-threshold').addEventListener('input', function() {
        document.getElementById('threshold-value').textContent = this.value + ' events';
    });
}

function updateCurrentTime() {
    const now = new Date();
    const timeString = now.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    const dateString = now.toLocaleDateString([], {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'});
    
    const timeElement = document.getElementById('current-time');
    if (timeElement) {
        timeElement.textContent = `${dateString} • ${timeString}`;
    }
}

function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const contentSections = document.querySelectorAll('.content-section');
    
    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            if (this.classList.contains('logout')) return;
            
            e.preventDefault();
            
            // Remove active class from all
            navItems.forEach(nav => nav.classList.remove('active'));
            contentSections.forEach(section => section.classList.remove('active'));
            
            // Add active class to clicked
            this.classList.add('active');
            
            // Show corresponding section
            const target = this.id.replace('nav-', '');
            const targetElement = document.getElementById(`${target}-content`);
            if (targetElement) {
                targetElement.classList.add('active');
            }
            document.getElementById('page-title').textContent = this.textContent.trim();
            
            currentPage = target;
            
            // Load data for the page
            switch(target) {
                case 'dashboard':
                    loadDashboardData();
                    loadRecentEvents();
                    break;
                case 'history':
                    loadHistory();
                    loadDashboardData();
                    break;
                case 'detection':
                    resetDetectionUI();
                    break;
                case 'wound-detection':
                    resetWoundDetectionUI();
                    break;
                case 'settings':
                    loadSettings();
                    break;
            }
        });
    });
}

async function loadDashboardData() {
    try {
        const response = await fetch(`/stats?username=${encodeURIComponent(currentUser)}`);
        if (response.ok) {
            const data = await response.json();

            // Update statistics
            const totalEventsEl = document.getElementById('total-events');
            const stressedEventsEl = document.getElementById('stressed-events');
            const woundEventsEl = document.getElementById('wound-events');
            const healthScoreEl = document.getElementById('health-score');

            if (totalEventsEl) totalEventsEl.textContent = data.total_events;
            if (stressedEventsEl) stressedEventsEl.textContent = data.stressed_events;
            if (woundEventsEl) woundEventsEl.textContent = data.wound_events;
            if (healthScoreEl) healthScoreEl.textContent = data.health_score + '%';

            // Update alert badge (if element exists)
            const alertCountEl = document.getElementById('alert-count');
            if (alertCountEl) {
                const alertCount = data.stressed_events;
                alertCountEl.textContent = alertCount > 9 ? '9+' : alertCount;
            }

            // Ensure charts exist and are initialized
            if (!stressChart || !timelineChart) {
                initializeCharts();
            }

            // Update charts with real data
            updateCharts(data);

            // Debug logs to verify chart data updates
            console.log('loadDashboardData', data);
        }
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    }
}

async function loadRecentEvents() {
    try {
        const response = await fetch(`/recent-events?username=${encodeURIComponent(currentUser)}`);
        if (response.ok) {
            const data = await response.json();
            const tbody = document.getElementById('recent-events-body');
            
            if (data.events && data.events.length > 0) {
                tbody.innerHTML = data.events.map(event => `
                    <tr>
                        <td>${formatDateTime(event.timestamp)}</td>
                        <td><span class="status-badge ${event.stress_class.toLowerCase()}">${event.stress_class}</span></td>
                        <td>
                            <div class="intensity-small">
                                <div class="intensity-bar" style="width: ${event.stress_intensity}%"></div>
                                <span>${event.stress_intensity}%</span>
                            </div>
                        </td>
                        <td>${(event.confidence * 100).toFixed(1)}%</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="4" class="no-events">No events recorded yet</td></tr>';
            }
        }
    } catch (error) {
        console.error('Error loading recent events:', error);
    }
}

function formatDateTime(datetimeString) {
    const date = new Date(datetimeString);
    return date.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function initializeCharts() {
    // Stress distribution chart - start with empty data for new users
    const stressCtx = document.getElementById('stressChart')?.getContext('2d');
    if (stressCtx) {
        stressChart = new Chart(stressCtx, {
            type: 'doughnut',
            data: {
                labels: ['Normal', 'Stressed'],
                datasets: [{
                    data: [1, 0], // Start with 1 normal, 0 stressed (will be updated)
                    backgroundColor: ['#51cf66', '#ff6b6b'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    }
                }
            }
        });
    }

    const timelineCtx = document.getElementById('timelineChart')?.getContext('2d');
    if (timelineCtx) {
        const today = new Date();
        const labels = [];
        for (let i = 6; i >= 0; i--) {
            const date = new Date(today);
            date.setDate(today.getDate() - i);
            labels.push(date.toLocaleDateString('en-US', { weekday: 'short' }));
        }

        timelineChart = new Chart(timelineCtx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Events',
                    data: [0, 0, 0, 0, 0, 0, 0], // Start with all zeros
                    backgroundColor: '#4a6fa5',
                    borderColor: '#3a5a8a',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                }
            }
        });
    }
}

function updateCharts(data) {
    if (!stressChart || !timelineChart) {
        console.warn('Charts not initialized, attempting to initialize...');
        initializeCharts();
        if (!stressChart || !timelineChart) {
            console.error('Failed to initialize charts');
            return;
        }
    }

    const stressed = parseInt(data.stressed_events ?? 0, 10);
    const total = parseInt(data.total_events ?? 0, 10);
    const normal = Math.max(0, total - stressed);

    console.log('Updating stress chart with:', {normal, stressed, total});
    if (stressChart) {
        stressChart.data.datasets[0].data = [normal, stressed];
        stressChart.update('none');
        console.log('Stress chart updated');
    }

    if (timelineChart) {
        const chartData = Array.isArray(data.chart_data) ? data.chart_data : [];
        console.log('Updating timeline chart with data:', chartData);

        if (chartData.length === 0) {
            const today = new Date();
            const zeroLabels = [];
            const zeroData = [];
            for (let i = 6; i >= 0; i--) {
                const d = new Date(today);
                d.setDate(today.getDate() - i);
                zeroLabels.push(d.toLocaleDateString('en-US', { weekday: 'short' }));
                zeroData.push(0);
            }
            timelineChart.data.labels = zeroLabels;
            timelineChart.data.datasets[0].data = zeroData;
        } else {
            // Ensure there are always exactly 7 points for the last 7 days.
            const expectedLabels = [];
            const expectedData = [];
            const today = new Date();
            for (let i = 6; i >= 0; i--) {
                const d = new Date(today);
                d.setDate(today.getDate() - i);
                expectedLabels.push(d.toLocaleDateString('en-US', { weekday: 'short' }));
                expectedData.push(0);
            }

            chartData.forEach(item => {
                const idx = expectedLabels.indexOf(item.date);
                if (idx >= 0) expectedData[idx] = parseInt(item.count ?? 0, 10);
            });

            timelineChart.data.labels = expectedLabels;
            timelineChart.data.datasets[0].data = expectedData;
        }
        timelineChart.update('none');
        console.log('Timeline chart updated');
    }

    console.log('updateCharts', data, 'stressed', stressed, 'normal', normal);
}

// File Selection Handler
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.type.startsWith('audio/')) {
        showError('Please select an audio file (WAV, MP3, etc.)');
        return;
    }
    
    selectedFile = file;
    
    // Show file info and analyze button
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    
    fileName.textContent = file.name;
    fileInfo.style.display = 'block';
    
    // Reset results if any
    document.getElementById('results-container').style.display = 'none';
}

// Analyze Uploaded Audio Button Handler
async function analyzeUploadedAudio() {
    if (!selectedFile) {
        showError('Please select an audio file first');
        return;
    }
    
    // Show loading state
    showLoadingState();
    
    const formData = new FormData();
    formData.append('audio_file', selectedFile);
    formData.append('username', currentUser);
    
    try {
        const response = await fetch('/upload-audio', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            displayResults(data);
            if (data.alert) {
                showAlert(data.alert);
            }
            // Refresh dashboard data
            loadDashboardData();
        } else {
            showError(data.error || 'Error processing audio');
        }
    } catch (error) {
        console.error('Upload error:', error);
        showError('Network error. Please try again.');
    } finally {
        hideLoadingState();
    }
}

// Cancel Upload Button Handler
function cancelUpload() {
    selectedFile = null;
    document.getElementById('file-info').style.display = 'none';
    document.getElementById('audio-upload').value = '';
    document.getElementById('results-container').style.display = 'none';
}

// Recording Functions
async function setupRecording() {
    const recordButton = document.getElementById('record-button');
    if (!recordButton) return;
    
    recordButton.addEventListener('click', toggleRecording);
}

async function toggleRecording() {
    if (!isRecording) {
        await startRecording();
    } else {
        stopRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };
        
        mediaRecorder.onstop = async () => {
            recordedAudio = new Blob(audioChunks, { type: 'audio/webm' });
            
            // Process the recording immediately
            await analyzeRecordedAudio();
            
            // Stop timer
            clearInterval(recordingTimer);
            document.getElementById('recording-timer').style.display = 'none';
        };
        
        mediaRecorder.start();
        isRecording = true;
        
        const recordButton = document.getElementById('record-button');
        recordButton.innerHTML = '<i class="fas fa-stop"></i> Stop Recording';
        recordButton.classList.add('recording');
        
        // Start recording timer
        recordingStartTime = Date.now();
        document.getElementById('recording-timer').style.display = 'block';
        updateRecordingTimer();
        recordingTimer = setInterval(updateRecordingTimer, 1000);
        
    } catch (error) {
        console.error('Recording error:', error);
        showError('Cannot access microphone. Please check permissions.');
    }
}

function updateRecordingTimer() {
    if (!recordingStartTime) return;
    
    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    
    document.getElementById('timer-display').textContent = 
        `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        
        const recordButton = document.getElementById('record-button');
        recordButton.innerHTML = '<i class="fas fa-circle"></i> Start Recording';
        recordButton.classList.remove('recording');
        
        // Stop all tracks
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
    }
}

// Analyze Recorded Audio Button Handler
async function analyzeRecordedAudio() {
    if (!recordedAudio) {
        showError('Please record audio first');
        return;
    }
    
    showLoadingState();
    
    // For this demo, we'll simulate analysis since we don't have real audio processing in frontend
    try {
        const formData = new FormData();
        formData.append('audio_data', 'simulated');
        formData.append('username', currentUser);
        
        const response = await fetch('/record-audio', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            displayResults(data);
            if (data.alert) {
                showAlert(data.alert);
            }
            // Refresh dashboard data
            loadDashboardData();
        } else {
            showError(data.error || 'Error processing audio');
        }
    } catch (error) {
        console.error('Upload error:', error);
        showError('Network error. Please try again.');
    } finally {
        hideLoadingState();
    }
}

// Results Display
function displayResults(data) {
    const resultsContainer = document.getElementById('results-container');
    resultsContainer.style.display = 'block';
    
    // Update results
    document.getElementById('stress-class').textContent = data.stress_class;
    document.getElementById('intensity-value').textContent = data.stress_intensity + '%';
    document.getElementById('intensity-bar').style.width = data.stress_intensity + '%';
    document.getElementById('confidence-value').textContent = (data.confidence * 100).toFixed(1) + '%';
    document.getElementById('timestamp-value').textContent = new Date(data.timestamp).toLocaleString();
    
    // Update status indicator
    const statusIndicator = document.querySelector('.status-indicator');
    const resultStatus = document.querySelector('.result-status');
    
    if (data.stress_class === 'Stressed') {
        statusIndicator.className = 'status-indicator stressed';
        statusIndicator.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
        resultStatus.querySelector('h2').style.color = '#ff6b6b';
        
        // Show recommendations based on intensity
        let recommendation = '';
        if (data.stress_intensity > 80) {
            recommendation = 'High stress detected! Consider contacting a veterinarian immediately.';
        } else if (data.stress_intensity > 50) {
            recommendation = 'Moderate stress detected. Monitor your pet closely and reduce environmental stressors.';
        } else {
            recommendation = 'Mild stress detected. Provide a calm environment and monitor behavior.';
        }
        document.getElementById('recommendation-text').textContent = recommendation;
    } else {
        statusIndicator.className = 'status-indicator normal';
        statusIndicator.innerHTML = '<i class="fas fa-check-circle"></i>';
        resultStatus.querySelector('h2').style.color = '#51cf66';
        document.getElementById('recommendation-text').textContent = 'Your pet appears calm and relaxed. Continue regular monitoring.';
    }
    
    // Scroll to results
    resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function resetDetectionUI() {
    document.getElementById('results-container').style.display = 'none';
    document.getElementById('file-info').style.display = 'none';
    selectedFile = null;
    recordedAudio = null;
}

// Wound Detection Functions
function initializeWoundDetection() {
    // Note: Wound detection event listeners are set up inline in index.html
    // to avoid duplicate listeners. All handlers are already attached there.
}

function handleWoundImageSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.type.startsWith('image/')) {
        showError('Please select an image file');
        return;
    }
    
    // Show file info
    const fileInfo = document.getElementById('wound-image-info');
    const fileName = document.getElementById('wound-image-name');
    
    fileName.textContent = file.name;
    fileInfo.style.display = 'block';
    
    // Reset results
    document.getElementById('wound-results-container').style.display = 'none';
}

function handleWoundVideoSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.type.startsWith('video/')) {
        showError('Please select a video file');
        return;
    }
    
    // Show file info
    const fileInfo = document.getElementById('wound-video-info');
    const fileName = document.getElementById('wound-video-name');
    
    fileName.textContent = file.name;
    fileInfo.style.display = 'block';
    
    // Reset results
    document.getElementById('wound-results-container').style.display = 'none';
}

async function analyzeWoundImage() {
    const fileInput = document.getElementById('wound-image-upload');
    if (!fileInput.files[0]) {
        showError('Please select an image first');
        return;
    }
    
    showLoadingState('Analyzing wound image...');
    
    const formData = new FormData();
    formData.append('image_file', fileInput.files[0]);
    formData.append('username', currentUser);
    
    try {
        const response = await fetch('/upload-wound-image', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            displayWoundResults(data);
        } else {
            showError(data.error || 'Error processing image');
        }
    } catch (error) {
        console.error('Wound image analysis error:', error);
        showError('Network error. Please try again.');
    } finally {
        hideLoadingState();
    }
}

async function analyzeWoundVideo() {
    const fileInput = document.getElementById('wound-video-upload');
    if (!fileInput.files[0]) {
        showError('Please select a video first');
        return;
    }
    
    showLoadingState('Analyzing wound video... This may take a moment.');
    
    const formData = new FormData();
    formData.append('video_file', fileInput.files[0]);
    formData.append('username', currentUser);
    
    try {
        const response = await fetch('/process-wound-video', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            displayWoundResults(data);
        } else {
            showError(data.error || 'Error processing video');
        }
    } catch (error) {
        console.error('Wound video analysis error:', error);
        showError('Network error. Please try again.');
    } finally {
        hideLoadingState();
    }
}

function displayWoundResults(data) {
    const resultsContainer = document.getElementById('wound-results-container');
    resultsContainer.style.display = 'block';
    
    // Update overall severity
    const severity = data.overall_severity;
    document.getElementById('wound-overall-severity').textContent = severity;
    
    // Update status indicator
    const statusIndicator = document.getElementById('wound-status-indicator');
    if (severity.includes('High')) {
        statusIndicator.className = 'status-indicator stressed';
        statusIndicator.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
        document.getElementById('wound-overall-severity').style.color = '#ff6b6b';
    } else if (severity.includes('Medium')) {
        statusIndicator.className = 'status-indicator warning';
        statusIndicator.innerHTML = '<i class="fas fa-exclamation-circle"></i>';
        document.getElementById('wound-overall-severity').style.color = '#ff922b';
    } else if (severity.includes('Low')) {
        statusIndicator.className = 'status-indicator warning';
        statusIndicator.innerHTML = '<i class="fas fa-info-circle"></i>';
        document.getElementById('wound-overall-severity').style.color = '#ffd43b';
    } else {
        statusIndicator.className = 'status-indicator normal';
        statusIndicator.innerHTML = '<i class="fas fa-check-circle"></i>';
        document.getElementById('wound-overall-severity').style.color = '#51cf66';
    }
    
    // Update wound types
    const woundTypes = data.wound_types || [];
    const woundTags = document.getElementById('wound-types-tags');
    if (woundTypes && woundTypes.length > 0) {
        woundTags.innerHTML = woundTypes.map(type => 
            `<span class="wound-tag ${type}">${type.replace('_', ' ')}</span>`
        ).join('');
    } else {
        woundTags.innerHTML = '<span class="wound-tag none">No wounds detected</span>';
    }
    
    // Update confidence
    const confidence = data.confidence || 0;
    document.getElementById('wound-confidence-value').textContent = 
        `${(confidence * 100).toFixed(1)}%`;
    
    // Update timestamp
    document.getElementById('wound-timestamp-value').textContent = 
        new Date(data.timestamp).toLocaleString();
    
    // Update recommendations
    const recommendationsList = document.getElementById('wound-recommendations-list');
    if (data.recommendations && data.recommendations.length > 0) {
        recommendationsList.innerHTML = data.recommendations.map(rec => 
            `<li>${rec}</li>`
        ).join('');
    } else {
        recommendationsList.innerHTML = '<li>No specific recommendations available</li>';
    }
    
    // Scroll to results
    resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function cancelWoundImage() {
    document.getElementById('wound-image-info').style.display = 'none';
    document.getElementById('wound-image-upload').value = '';
    document.getElementById('wound-results-container').style.display = 'none';
}

function cancelWoundVideo() {
    document.getElementById('wound-video-info').style.display = 'none';
    document.getElementById('wound-video-upload').value = '';
    document.getElementById('wound-results-container').style.display = 'none';
}

function resetWoundDetectionUI() {
    cancelWoundImage();
    cancelWoundVideo();
}

// History Functions
async function loadHistory() {
    await loadStressHistory();
    await loadWoundHistory();

    // keep dashboard metrics/charts in sync when user visits history
    await loadDashboardData();
}

async function loadStressHistory() {
    try {
        const response = await fetch(`/recent-events?username=${encodeURIComponent(currentUser)}`);
        if (response.ok) {
            const data = await response.json();
            updateStressHistoryTable(data.events || []);
        }
    } catch (error) {
        console.error('Error loading stress history:', error);
    }
}

async function loadWoundHistory() {
    try {
        const response = await fetch(`/wound-history?username=${encodeURIComponent(currentUser)}`);
        if (response.ok) {
            const data = await response.json();
            updateWoundHistoryTable(data.events || []);
        }
    } catch (error) {
        console.error('Error loading wound history:', error);
    }
}

function updateStressHistoryTable(events) {
    const tbody = document.getElementById('stress-history-table-body');
    
    if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-events">No stress events found</td></tr>';
        return;
    }
    
    tbody.innerHTML = events.map(event => `
        <tr>
            <td>${formatDateTime(event.timestamp)}</td>
            <td><span class="status-badge ${event.stress_class.toLowerCase()}">${event.stress_class}</span></td>
            <td>
                <div class="intensity-small">
                    <div class="intensity-bar" style="width: ${event.stress_intensity}%"></div>
                    <span>${event.stress_intensity}%</span>
                </div>
            </td>
            <td>${(event.confidence * 100).toFixed(1)}%</td>
        </tr>
    `).join('');
}

function updateWoundHistoryTable(events) {
    const tbody = document.getElementById('wound-history-table-body');
    
    if (events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-events">No wound events found</td></tr>';
        return;
    }
    
    tbody.innerHTML = events.map(event => `
        <tr>
            <td>${formatDateTime(event.timestamp)}</td>
            <td>${event.wound_types.map(type => `<span class="wound-tag ${type}">${type.replace('_', ' ')}</span>`).join(' ')}</td>
            <td><span class="severity-badge ${event.severity.toLowerCase().replace(' ', '-')}">${event.severity}</span></td>
            <td>${(event.confidence * 100).toFixed(1)}%</td>
        </tr>
    `).join('');
}

function showHistoryTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(`${tabName}-history`).classList.add('active');
    
    // Activate button
    event.target.classList.add('active');
}

// Settings Functions
async function loadSettings() {
    try {
        const response = await fetch(`/get-settings?username=${encodeURIComponent(currentUser)}`);
        if (response.ok) {
            const data = await response.json();
            const settings = data.settings;
            
            // Populate form fields
            document.getElementById('alert-threshold').value = settings.alert_threshold;
            document.getElementById('threshold-value').textContent = settings.alert_threshold + ' events';
            document.getElementById('email-notifications').checked = settings.email_notifications;
            document.getElementById('recipient-email').value = settings.recipient_email || '';
            document.getElementById('smtp-server').value = settings.smtp_server;
            document.getElementById('smtp-port').value = settings.smtp_port;
            document.getElementById('smtp-username').value = settings.smtp_username || '';
            document.getElementById('smtp-password').value = settings.smtp_password || '';
            document.getElementById('sender-email').value = settings.sender_email || '';
        }
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

async function saveSettings() {
    const settings = {
        alert_threshold: document.getElementById('alert-threshold').value,
        email_enabled: document.getElementById('email-notifications').checked,
        recipient_email: document.getElementById('recipient-email').value,
        smtp_server: document.getElementById('smtp-server').value,
        smtp_port: document.getElementById('smtp-port').value,
        smtp_username: document.getElementById('smtp-username').value,
        smtp_password: document.getElementById('smtp-password').value,
        sender_email: document.getElementById('sender-email').value
    };
    
    // Validate email settings if enabled
    if (settings.email_enabled) {
        if (!settings.recipient_email) {
            showError('Please enter a recipient email address');
            return;
        }
    }
    
    const formData = new FormData();
    formData.append('username', currentUser);
    Object.keys(settings).forEach(key => {
        formData.append(key, settings[key]);
    });
    
    try {
        const response = await fetch('/update-settings', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Settings saved successfully!', 'success');
        } else {
            showError(data.error || 'Error saving settings');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        showError('Network error. Please try again.');
    }
}

// Utility Functions
function showLoadingState(message = 'Processing...') {
    let loading = document.getElementById('loading-overlay');
    if (!loading) {
        loading = document.createElement('div');
        loading.id = 'loading-overlay';
        loading.className = 'loading-overlay';
        loading.innerHTML = `
            <div class="loading-spinner">
                <i class="fas fa-paw fa-spin"></i>
                <p>${message}</p>
            </div>
        `;
        document.body.appendChild(loading);
    } else {
        loading.querySelector('p').textContent = message;
    }
    loading.style.display = 'flex';
}

function hideLoadingState() {
    const loading = document.getElementById('loading-overlay');
    if (loading) {
        loading.style.display = 'none';
    }
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-notification';
    errorDiv.innerHTML = `
        <i class="fas fa-exclamation-circle"></i>
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">&times;</button>
    `;
    
    document.body.appendChild(errorDiv);
    
    setTimeout(() => {
        if (errorDiv.parentElement) {
            errorDiv.remove();
        }
    }, 5000);
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : 'info-circle'}"></i>
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">&times;</button>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 3000);
}

function showAlert(message) {
    const alertBox = document.getElementById('alert-box');
    const alertMessage = document.getElementById('alert-message');
    
    alertMessage.textContent = message;
    alertBox.style.display = 'block';
    
    alertBox.scrollIntoView({ behavior: 'smooth' });
}

function dismissAlert() {
    document.getElementById('alert-box').style.display = 'none';
}

function showWoundAlert(message) {
    const alertBox = document.getElementById('wound-alert-box');
    const alertMessage = document.getElementById('wound-alert-message');
    
    alertMessage.textContent = message;
    alertBox.style.display = 'block';
    
    alertBox.scrollIntoView({ behavior: 'smooth' });
}

function dismissWoundAlert() {
    document.getElementById('wound-alert-box').style.display = 'none';
}