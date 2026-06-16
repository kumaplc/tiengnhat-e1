(function() {
    let appData = null;
    let vocabList = [];
    let grammarList = [];
    let fcIndex = 0;
    const vocabMap = {};
    let currentJLPT = 'all';
    let savedArticles = JSON.parse(localStorage.getItem('jp_saved_articles') || '[]');
    let fcMeaningVisible = false;
    
    // Starred map: lưu các từ cần ôn tập
    let starredMap = JSON.parse(localStorage.getItem('jp_starred_map') || '{}');
    function saveStarredMap() { localStorage.setItem('jp_starred_map', JSON.stringify(starredMap)); }
    function syncStarredToVocab() {
        for (let v of vocabList) {
            if (starredMap[v.word] !== undefined) v.starred = starredMap[v.word];
            else v.starred = false;
        }
    }
    function toggleStar(word) {
        const newState = !starredMap[word];
        starredMap[word] = newState;
        saveStarredMap();
        const vocabItem = vocabList.find(v => v.word === word);
        if (vocabItem) vocabItem.starred = newState;
        // Cập nhật UI nếu đang ở các panel liên quan
        const activeMain = document.querySelector('.main-panel.active');
        if (activeMain && activeMain.id === 'panel-learn') {
            const activeSub = document.querySelector('.sub-panel.active');
            if (activeSub) {
                if (activeSub.id === 'sub-flashcard') updateFlashcardUI();
                else if (activeSub.id === 'sub-vocab') renderVocabList();
                else if (activeSub.id === 'sub-quiz') updateQuizUI();
            }
        }
        showToast(newState ? '⭐ Đã thêm vào ôn tập' : '☆ Đã bỏ khỏi ôn tập');
    }

    // Quiz variables
    let quizWords = [];
    let quizAnswers = [];
    let quizCurrentIndex = 0;

    function showToast(msg) {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 2100);
    }

    function getEasyExample(wordObj, type = 'vocab') {
        if (type === 'vocab') {
            if (wordObj.example && wordObj.example.length < 60) return wordObj.example;
            const easyExamples = {
                '食べる': '私は毎日ご飯を食べます。',
                '飲む': '水を飲みます。',
                '行く': '学校へ行きます。',
                '見る': 'テレビを見ます。',
                '聞く': '音楽を聞きます。',
                '話す': '日本語を話します。',
                '読む': '本を読みます。',
                '書く': '手紙を書きます。',
                '買う': 'スーパーで買い物を買います。',
                '作る': '料理を作ります。'
            };
            if (easyExamples[wordObj.word]) return easyExamples[wordObj.word];
            return `Ví dụ: ${wordObj.word} là từ vựng tiếng Nhật.`;
        } else {
            if (wordObj.example && wordObj.example.length < 60) return wordObj.example;
            return `Ví dụ: ${wordObj.pattern} được sử dụng trong câu.`;
        }
    }

    function autoSaveCurrentArticle() {
        if (!appData) return;
        const title = appData.title || 'Bài học ' + new Date().toLocaleDateString();
        const existingIndex = savedArticles.findIndex(a => a.title === title && a.fullText === appData.fullText);
        if (existingIndex >= 0) {
            savedArticles[existingIndex] = { ...appData, savedAt: new Date().toISOString() };
        } else {
            savedArticles.push({ ...appData, savedAt: new Date().toISOString() });
        }
        localStorage.setItem('jp_saved_articles', JSON.stringify(savedArticles));
    }

    // TABS
    function switchMainTab(tabName) {
        document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
        const activeTab = document.querySelector(`.main-tab[data-tab="${tabName}"]`);
        if (activeTab) activeTab.classList.add('active');
        document.querySelectorAll('.main-panel').forEach(p => p.classList.remove('active'));
        const activePanel = document.getElementById(`panel-${tabName}`);
        if (activePanel) activePanel.classList.add('active');
        if (tabName === 'learn') switchSubTab('read');
        if (tabName === 'saved') renderSavedList();
    }

    function switchSubTab(subName) {
        document.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
        const activeSubTab = document.querySelector(`.sub-tab[data-sub="${subName}"]`);
        if (activeSubTab) activeSubTab.classList.add('active');
        document.querySelectorAll('.sub-panel').forEach(p => p.classList.remove('active'));
        const activeSubPanel = document.getElementById(`sub-${subName}`);
        if (activeSubPanel) activeSubPanel.classList.add('active');
        // Cập nhật số lượng và render
        applyJLPTFilter(); // cập nhật filteredCount
        if (subName === 'flashcard') { fcIndex = 0; updateFlashcardUI(); }
        else if (subName === 'quiz') updateQuizUI();
        else if (subName === 'vocab') renderVocabList();
        else if (subName === 'grammar') renderGrammarList();
        // sub-read không cần render gì thêm
    }

    document.querySelectorAll('.main-tab').forEach(tab => tab.addEventListener('click', () => switchMainTab(tab.dataset.tab)));
    document.querySelectorAll('.sub-tab').forEach(tab => tab.addEventListener('click', () => switchSubTab(tab.dataset.sub)));

    function applyJLPTFilter() {
        const filterSelect = document.getElementById('jlptFilter');
        currentJLPT = filterSelect ? filterSelect.value : 'all';
        let filtered = [];
        if (currentJLPT === 'starred') filtered = vocabList.filter(v => v.starred === true);
        else if (currentJLPT === 'all') filtered = vocabList;
        else filtered = vocabList.filter(v => v.jlpt === currentJLPT);
        const filteredCountSpan = document.getElementById('filteredCount');
        if (filteredCountSpan) filteredCountSpan.textContent = vocabList.length > 0 ? `(${filtered.length} từ)` : '';
        return filtered;
    }

    const filterSelect = document.getElementById('jlptFilter');
    if (filterSelect) {
        filterSelect.addEventListener('change', () => {
            if (document.getElementById('panel-learn')?.classList.contains('active')) {
                // Cập nhật số lượng
                const filtered = applyJLPTFilter();
                const activeSub = document.querySelector('.sub-panel.active');
                if (activeSub) {
                    if (activeSub.id === 'sub-vocab') renderVocabList();
                    else if (activeSub.id === 'sub-flashcard') { fcIndex = 0; updateFlashcardUI(); }
                    else if (activeSub.id === 'sub-quiz') updateQuizUI();
                    // sub-read và sub-grammar không bị ảnh hưởng bởi filter
                }
            }
        });
    }

    // PROMPT
    document.getElementById('btnGeneratePrompt')?.addEventListener('click', () => {
        const text = document.getElementById('inputText')?.value.trim();
        if (!text) { showToast('⚠️ Nhập nội dung bài đọc.'); return; }
        const prompt = `Bạn là trợ lý dạy tiếng Nhật. Hãy phân tích đoạn văn sau và trả về **chính xác** một đối tượng JSON (không markdown, không văn bản thừa) theo cấu trúc:

{
  "title": "Tiêu đề phù hợp (tiếng Việt)",
  "fullText": "toàn bộ đoạn văn gốc (giữ nguyên)",
  "vocabulary": [
    { "word": "...", "reading": "...", "meaning": "...", "jlpt": "...", "example": "..." }
  ],
  "grammar": [
    { "pattern": "...", "meaning": "...", "example": "...", "note": "..." }
  ]
}

Yêu cầu: liệt kê tất cả từ vựng, nghĩa sát ngữ cảnh, chỉ trả về JSON thuần.

Đoạn văn:
"""
${text}
"""`;
        const promptBox = document.getElementById('promptBox');
        if (promptBox) promptBox.textContent = prompt;
        const container = document.getElementById('promptContainer');
        if (container) container.style.display = 'block';
        showToast('✅ Prompt đã tạo. Nhấn nút Copy.');
    });

    document.getElementById('btnCopyPrompt')?.addEventListener('click', () => {
        const promptBox = document.getElementById('promptBox');
        if (promptBox) navigator.clipboard.writeText(promptBox.textContent).then(() => showToast('📋 Đã copy!'));
    });

    document.getElementById('btnFetchUrl')?.addEventListener('click', async function() {
        const url = document.getElementById('urlInput')?.value.trim();
        if (!url) return;
        this.textContent = '⏳'; this.disabled = true;
        try {
            const proxies = [
                `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`,
                `https://corsproxy.io/?${encodeURIComponent(url)}`,
                `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}`
            ];
            let html = null;
            for (const proxy of proxies) {
                try {
                    const r = await fetch(proxy, { signal: AbortSignal.timeout(15000) });
                    if (r.ok) { html = await r.text(); break; }
                } catch(e) {}
            }
            if (!html) {
                try { const r = await fetch(url, { signal: AbortSignal.timeout(10000) }); if (r.ok) html = await r.text(); } catch(e) {}
            }
            if (!html) { alert('Không tải được URL.'); return; }
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const main = doc.querySelector('article, .entry-content, main, body');
            if (main) {
                main.querySelectorAll('script, style, nav, footer, header').forEach(el => el.remove());
                const inputText = document.getElementById('inputText');
                if (inputText) inputText.value = main.textContent.replace(/\s{2,}/g, '\n').trim();
                showToast('✅ Đã lấy nội dung.');
            }
        } catch(e) { alert('Lỗi: ' + e.message); }
        finally { this.textContent = '🌐 Tải'; this.disabled = false; }
    });

    // LOAD JSON
    function loadFromJSON(json) {
        if (!json.fullText || !json.vocabulary) {
            alert('JSON không hợp lệ: thiếu fullText hoặc vocabulary');
            return;
        }
        appData = json;
        vocabList = json.vocabulary || [];
        grammarList = json.grammar || [];
        for (let k in vocabMap) delete vocabMap[k];
        for (const v of vocabList) {
            vocabMap[v.word] = v;
            if (starredMap[v.word] !== undefined) v.starred = starredMap[v.word];
            else v.starred = false;
        }
        syncStarredToVocab();
        
        const tabLearn = document.getElementById('tabLearn');
        const filterBar = document.getElementById('jlptFilterBar');
        if (tabLearn) tabLearn.style.display = 'inline-flex';
        if (filterBar) filterBar.style.display = 'flex';
        
        updateAllUI();
        autoSaveCurrentArticle();
        switchMainTab('learn');
        showToast('✅ Dữ liệu đã sẵn sàng và tự động lưu!');
    }

    document.getElementById('btnLoadJson')?.addEventListener('click', () => {
        const raw = document.getElementById('jsonInput')?.value.trim();
        if (!raw) { showToast('⚠️ Dán JSON vào ô bên trên.'); return; }
        let json = null;
        try { json = JSON.parse(raw); } catch(e) {
            const cleaned = raw.replace(/```json\s*|\s*```/g, '').trim();
            try { json = JSON.parse(cleaned); } catch(e2) { alert('JSON không hợp lệ.\n' + e2.message); return; }
        }
        loadFromJSON(json);
    });

    function renderSavedList() {
        const list = document.getElementById('savedList');
        const empty = document.getElementById('savedEmpty');
        if (!list || !empty) return;
        if (savedArticles.length === 0) { list.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        list.innerHTML = savedArticles.map((a, i) => `
            <div class="saved-item">
                <div>
                    <div class="title">${escapeHtml(a.title || 'Không tiêu đề')}</div>
                    <div style="font-size:0.85rem; color:var(--sub);">${a.vocabulary?.length || 0} từ, ${a.grammar?.length || 0} ngữ pháp</div>
                </div>
                <div class="actions">
                    <button class="btn btn-small btn-primary" data-idx="${i}">📂 Mở</button>
                    <button class="btn btn-small btn-outline" data-idx="${i}" data-action="delete">🗑 Xóa</button>
                </div>
            </div>
        `).join('');
        list.querySelectorAll('button').forEach(btn => {
            const idx = parseInt(btn.dataset.idx);
            if (btn.dataset.action === 'delete') {
                btn.addEventListener('click', () => {
                    savedArticles.splice(idx, 1);
                    localStorage.setItem('jp_saved_articles', JSON.stringify(savedArticles));
                    renderSavedList();
                    showToast('🗑 Đã xóa bài.');
                });
            } else {
                btn.addEventListener('click', () => {
                    loadFromJSON(savedArticles[idx]);
                });
            }
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    function updateAllUI() {
        renderArticle();
        renderVocabList();
        renderGrammarList();
        updateCounts();
        updateFlashcardUI();
        updateQuizUI();
        applyJLPTFilter(); // cập nhật số lượng
    }

    function updateCounts() {
        const vocabSpan = document.getElementById('vocabCount');
        const grammarSpan = document.getElementById('grammarCount');
        if (vocabSpan) vocabSpan.textContent = vocabList.length;
        if (grammarSpan) grammarSpan.textContent = grammarList.length;
    }

    function renderArticle() {
        const container = document.getElementById('articleContent');
        if (!container) return;
        if (!appData?.fullText) { container.textContent = 'Chưa có bài đọc. Hãy tải JSON lên.'; return; }
        const sorted = vocabList.map(v=>v.word).sort((a,b)=>b.length-a.length);
        if(!sorted.length){ container.textContent = appData.fullText; return; }
        const escaped = sorted.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
        const regex = new RegExp(`(${escaped.join('|')})`, 'g');
        container.innerHTML = appData.fullText.replace(regex, (match) => {
            if(vocabMap[match]) return `<span class="word" data-word="${match}">${match}</span>`;
            return match;
        });
        container.querySelectorAll('span.word').forEach(span => span.addEventListener('click', (e) => {
            e.stopPropagation();
            const v = vocabMap[span.dataset.word];
            if(v) showTooltip(e, v);
        }));
        document.addEventListener('click', (e) => { if(!e.target.classList.contains('word')) document.getElementById('wordTooltip').style.display='none'; });
    }

    function showTooltip(event, vocab) {
        const tip = document.getElementById('wordTooltip');
        if (!tip) return;
        tip.innerHTML = `
            <div class="jp">${escapeHtml(vocab.word)}</div>
            <div class="reading">${escapeHtml(vocab.reading || '')}</div>
            <div class="meaning">${escapeHtml(vocab.meaning || '')}</div>
            ${vocab.example ? `<div class="example">📖 ${escapeHtml(vocab.example)}</div>` : ''}
            ${vocab.jlpt ? `<span class="tag" style="margin-top:4px;">${vocab.jlpt}</span>` : ''}
        `;
        tip.style.left = Math.min(event.clientX+10, window.innerWidth-340)+'px';
        tip.style.top = Math.max(event.clientY-40, 10)+'px';
        tip.style.display = 'block';
    }

    function renderVocabList() {
        const list = document.getElementById('vocabList'), empty = document.getElementById('vocabEmpty');
        if (!list || !empty) return;
        const filtered = applyJLPTFilter(); // vừa lọc vừa cập nhật số lượng
        if(filtered.length===0){ list.innerHTML=''; empty.style.display='block'; return; }
        empty.style.display='none';
        list.innerHTML = filtered.map(v => {
            const starred = v.starred ? 'starred' : '';
            const starChar = v.starred ? '★' : '☆';
            return `<li class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div><span class="jp">${escapeHtml(v.word)}</span><span class="reading">${escapeHtml(v.reading||'')}</span></div>
                    <span class="star-icon-list ${starred}" data-word="${escapeHtml(v.word)}" style="cursor:pointer; font-size:22px;">${starChar}</span>
                </div>
                <div>${escapeHtml(v.meaning||'')}</div>
                ${v.jlpt?`<span class="tag">${v.jlpt}</span>`:''}
                <div style="font-size:0.85rem; color:var(--sub); margin-top:6px;">📖 ${escapeHtml(getEasyExample(v, 'vocab'))}</div>
            </li>`;
        }).join('');
        // Gắn sự kiện click cho từng sao
        document.querySelectorAll('.star-icon-list').forEach(el => {
            const word = el.dataset.word;
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleStar(word);
                renderVocabList(); // refresh lại danh sách
            });
        });
    }
    
    function renderGrammarList() {
        const list = document.getElementById('grammarList'), empty = document.getElementById('grammarEmpty');
        if (!list || !empty) return;
        if(grammarList.length===0){ list.innerHTML=''; empty.style.display='block'; return; }
        empty.style.display='none';
        list.innerHTML = grammarList.map(g=>`<li class="card">
            <div class="jp">${escapeHtml(g.pattern)}</div>
            <div>${escapeHtml(g.meaning)}</div>
            ${g.example?`<div>📖 ${escapeHtml(g.example)}</div>`:`<div style="font-size:0.85rem; color:var(--sub);">📖 ${escapeHtml(getEasyExample(g, 'grammar'))}</div>`}
            ${g.note?`<div style="font-size:0.8rem;">💡 ${escapeHtml(g.note)}</div>`:''}
        </li>`).join('');
    }

    // FLASHCARD
    function getFilteredVocab() { 
        if (currentJLPT === 'starred') return vocabList.filter(v => v.starred === true);
        if (currentJLPT === 'all') return vocabList;
        return vocabList.filter(v => v.jlpt === currentJLPT);
    }
    
    function updateFlashcardUI() {
        const filtered = getFilteredVocab();
        const fcWord = document.getElementById('fcWord');
        const fcReading = document.getElementById('fcReading');
        const fcMeaning = document.getElementById('fcMeaning');
        const fcBack = document.getElementById('fcBack');
        const fcProgress = document.getElementById('fcProgress');
        const starIcon = document.getElementById('starIcon');
        if (!fcWord || !fcReading || !fcMeaning || !fcBack || !fcProgress) return;
        
        if (filtered.length === 0) {
            fcWord.textContent = '?';
            fcReading.textContent = '';
            fcMeaning.textContent = '';
            fcProgress.textContent = '0/0';
            fcBack.style.opacity = '0';
            fcBack.style.visibility = 'hidden';
            if (starIcon) starIcon.style.display = 'none';
            return;
        }
        if (starIcon) starIcon.style.display = 'block';
        if (fcIndex >= filtered.length) fcIndex = 0;
        const v = filtered[fcIndex];
        fcWord.textContent = v.word;
        fcReading.textContent = v.reading || '';
        fcMeaning.textContent = v.meaning || '';
        fcProgress.textContent = `${fcIndex+1}/${filtered.length}`;
        
        // Cập nhật ngôi sao
        if (starIcon) {
            starIcon.textContent = v.starred ? '★' : '☆';
            starIcon.classList.toggle('starred', v.starred);
            // Xóa event cũ để tránh trùng, gán mới
            const newStar = starIcon.cloneNode(true);
            starIcon.parentNode.replaceChild(newStar, starIcon);
            const newStarIcon = document.getElementById('starIcon');
            if (newStarIcon) {
                newStarIcon.onclick = () => toggleStar(v.word);
            }
        }
        
        fcMeaningVisible = false;
        fcBack.style.opacity = '0';
        fcBack.style.visibility = 'hidden';
    }

    function toggleMeaning() {
        fcMeaningVisible = !fcMeaningVisible;
        const fcBack = document.getElementById('fcBack');
        if (fcBack) {
            fcBack.style.opacity = fcMeaningVisible ? '1' : '0';
            fcBack.style.visibility = fcMeaningVisible ? 'visible' : 'hidden';
        }
    }

    document.getElementById('btnPrevCard')?.addEventListener('click', () => {
        const f = getFilteredVocab();
        if (f.length) { fcIndex = (fcIndex - 1 + f.length) % f.length; updateFlashcardUI(); }
    });
    document.getElementById('btnNextCard')?.addEventListener('click', () => {
        const f = getFilteredVocab();
        if (f.length) { fcIndex = (fcIndex + 1) % f.length; updateFlashcardUI(); }
    });
    document.getElementById('btnToggleMeaning')?.addEventListener('click', toggleMeaning);

    // Focus Mode
    function enableFocusMode() {
        document.body.classList.add('focus-mode');
        document.getElementById('btnFocusMode').style.display = 'none';
        document.getElementById('exitFocusBtn').style.display = 'block';
    }
    function disableFocusMode() {
        document.body.classList.remove('focus-mode');
        document.getElementById('btnFocusMode').style.display = 'inline-flex';
        document.getElementById('exitFocusBtn').style.display = 'none';
    }
    document.getElementById('btnFocusMode')?.addEventListener('click', enableFocusMode);
    document.getElementById('btnExitFocus')?.addEventListener('click', disableFocusMode);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.body.classList.contains('focus-mode')) {
            disableFocusMode();
        }
    });

    // QUIZ
    function updateQuizUI() {
        const area = document.getElementById('quizArea'), empty = document.getElementById('quizEmpty');
        const filtered = getFilteredVocab();
        if (!area || !empty) return;
        if (filtered.length < 4) { area.style.display = 'none'; empty.style.display = 'block'; return; }
        empty.style.display = 'none'; area.style.display = 'block';
        
        const maxQuestions = Math.min(10, filtered.length);
        const shuffled = [...filtered];
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        quizWords = shuffled.slice(0, maxQuestions);
        quizAnswers = new Array(quizWords.length).fill(false);
        quizCurrentIndex = 0;
        
        const progressBar = document.getElementById('quizProgressBar');
        const progressText = document.getElementById('quizProgressText');
        if (progressBar) progressBar.style.width = '0%';
        if (progressText) progressText.textContent = `0/${quizWords.length}`;
        
        document.getElementById('quizSummary').style.display = 'none';
        displayQuizQuestion();
    }

    function displayQuizQuestion() {
        if (quizCurrentIndex >= quizWords.length) {
            endQuiz();
            return;
        }
        const currentWord = quizWords[quizCurrentIndex];
        document.getElementById('quizWord').textContent = currentWord.word;
        
        const allVocab = getFilteredVocab();
        const otherWords = allVocab.filter(w => w.word !== currentWord.word);
        const options = [currentWord];
        while (options.length < 4 && otherWords.length) {
            const randIndex = Math.floor(Math.random() * otherWords.length);
            options.push(otherWords[randIndex]);
            otherWords.splice(randIndex, 1);
        }
        for (let i = options.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [options[i], options[j]] = [options[j], options[i]];
        }
        
        const optsDiv = document.getElementById('quizOptions');
        optsDiv.innerHTML = options.map((opt, idx) => `
            <div class="quiz-option" data-word="${escapeHtml(opt.word)}">
                <span class="option-number">${idx+1}.</span> ${escapeHtml(opt.meaning || '(chưa có nghĩa)')}
            </div>
        `).join('');
        
        document.querySelectorAll('.quiz-option').forEach(opt => {
            opt.classList.remove('correct', 'wrong', 'disabled');
            opt.style.pointerEvents = 'auto';
            opt.addEventListener('click', function handler() {
                if (this.classList.contains('disabled')) return;
                const selectedWord = this.dataset.word;
                const isCorrect = (selectedWord === currentWord.word);
                quizAnswers[quizCurrentIndex] = isCorrect;
                if (isCorrect) {
                    this.classList.add('correct');
                    document.getElementById('quizResult').innerHTML = '✅ Chính xác!';
                } else {
                    this.classList.add('wrong');
                    document.getElementById('quizResult').innerHTML = `❌ Sai rồi! Đáp án đúng là: ${escapeHtml(currentWord.meaning)}`;
                    document.querySelectorAll('.quiz-option').forEach(opt2 => {
                        if (opt2.dataset.word === currentWord.word) opt2.classList.add('correct');
                    });
                }
                document.querySelectorAll('.quiz-option').forEach(opt2 => {
                    opt2.classList.add('disabled');
                    opt2.style.pointerEvents = 'none';
                });
                const percent = ((quizCurrentIndex + 1) / quizWords.length) * 100;
                const progressBar = document.getElementById('quizProgressBar');
                const progressText = document.getElementById('quizProgressText');
                if (progressBar) progressBar.style.width = `${percent}%`;
                if (progressText) progressText.textContent = `${quizCurrentIndex+1}/${quizWords.length}`;
            });
        });
        document.getElementById('quizResult').innerHTML = '';
    }

    function nextQuizQuestion() {
        if (quizCurrentIndex < quizWords.length) {
            const answered = Array.from(document.querySelectorAll('.quiz-option')).some(opt => opt.classList.contains('correct') || opt.classList.contains('wrong'));
            if (!answered) {
                showToast('⚠️ Hãy chọn đáp án trước khi sang câu tiếp!');
                return;
            }
            quizCurrentIndex++;
            displayQuizQuestion();
        } else {
            endQuiz();
        }
    }

    function endQuiz() {
        const total = quizAnswers.length;
        const correct = quizAnswers.filter(a => a === true).length;
        const percent = Math.round((correct / total) * 100);
        let icon = '';
        let message = '';
        if (percent === 100) { icon = '🎉🔥🌟'; message = 'Hoàn hảo! Bạn thật sự xuất sắc!'; }
        else if (percent >= 80) { icon = '🔥👍'; message = 'Rất tốt! Gần như thuộc bài rồi!'; }
        else if (percent >= 60) { icon = '📖✨'; message = 'Khá ổn, hãy ôn lại một chút nữa nhé!'; }
        else { icon = '💪📚'; message = 'Cố gắng hơn nữa! Ôn lại từ vựng và thử lại.'; }
        
        const summaryHtml = `
            <div style="text-align:center; margin-top:20px;">
                <h3>${icon} KẾT THÚC QUIZ ${icon}</h3>
                <p style="font-size:1.5rem; font-weight:bold;">Bạn đã làm đúng <span style="color:#27ae60;">${correct}</span> / ${total} câu</p>
                <p>${message}</p>
                <button class="btn btn-primary" id="restartQuizBtn">🔄 Làm lại</button>
            </div>
        `;
        document.getElementById('quizSummary').innerHTML = summaryHtml;
        document.getElementById('quizArea').style.display = 'none';
        document.getElementById('quizSummary').style.display = 'block';
        document.getElementById('restartQuizBtn')?.addEventListener('click', () => {
            document.getElementById('quizSummary').style.display = 'none';
            updateQuizUI();
        });
    }

    document.getElementById('btnNextQuiz')?.addEventListener('click', nextQuizQuestion);

    // PHÍM TẮT
    document.addEventListener('keydown', (e) => {
        const activeMain = document.querySelector('.main-panel.active');
        if (!activeMain || activeMain.id !== 'panel-learn') return;
        const activeSub = document.querySelector('.sub-panel.active');
        if (!activeSub) return;
        
        if (activeSub.id === 'sub-flashcard') {
            const filtered = getFilteredVocab();
            if (filtered.length === 0) return;
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                fcIndex = (fcIndex - 1 + filtered.length) % filtered.length;
                updateFlashcardUI();
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                fcIndex = (fcIndex + 1) % filtered.length;
                updateFlashcardUI();
            } else if (e.key === ' ' || e.key === 'Space') {
                e.preventDefault();
                toggleMeaning();
            }
        } else if (activeSub.id === 'sub-quiz') {
            const quizArea = document.getElementById('quizArea');
            const quizSummary = document.getElementById('quizSummary');
            if (quizArea && quizArea.style.display === 'block') {
                if (e.key === ' ' || e.key === 'Space' || e.key === 'ArrowRight') {
                    e.preventDefault();
                    nextQuizQuestion();
                }
            }
        }
    });

    // KHỞI TẠO MẶC ĐỊNH
    function initDefaultLearnPanel() {
        const tabLearn = document.getElementById('tabLearn');
        const filterBar = document.getElementById('jlptFilterBar');
        if (tabLearn) tabLearn.style.display = 'inline-flex';
        if (filterBar) filterBar.style.display = 'flex';
        
        if (!appData) {
            appData = {
                fullText: `Chào mừng bạn đến với công cụ học tiếng Nhật!

Hãy bắt đầu bằng cách:
1️⃣ Dán một đoạn văn bản tiếng Nhật vào tab "Nhập liệu & Prompt"
2️⃣ Nhấn "Tạo Prompt" và copy nội dung
3️⃣ Gửi cho AI (ChatGPT, Gemini,...) để nhận JSON
4️⃣ Dán JSON vào tab "Dán JSON & Học" và nhấn "Xử lý & Học"

✨ Sau khi tải dữ liệu, bạn có thể:
- Học từ vựng và ngữ pháp
- Ôn tập với Flashcard (phím ← → và Space)
- Làm bài tập Quiz (phím 1-4 và Space/→)
- Lọc theo cấp độ JLPT hoặc chỉ xem từ đã đánh dấu sao ⭐

Chúc bạn học tốt! 🎌`,
                vocabulary: [],
                grammar: [],
                title: 'Hướng dẫn sử dụng'
            };
            vocabList = [];
            grammarList = [];
            updateAllUI();
        }
    }
    
    initDefaultLearnPanel();
    renderSavedList();
})();