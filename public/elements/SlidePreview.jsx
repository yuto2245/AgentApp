import React, { useState, useEffect, useMemo, useRef } from 'react';

// Dynamically load a script and return a promise
const loadScript = (src) => {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load script: ${src}`));
    document.head.appendChild(script);
  });
};

const styles = `
  .slide-preview-container {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #333;
    color: #fff;
  }
  .slide-render-area {
    flex-grow: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .slide-content {
    background: #fff;
    color: #000;
    width: 100%;
    height: 100%;
    max-width: 1280px;
    max-height: 720px;
    aspect-ratio: 16 / 9;
    padding: 40px;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    overflow: auto;
  }
  .controls {
    flex-shrink: 0;
    padding: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #222;
    border-top: 1px solid #444;
  }
  .controls button, .controls span {
    margin: 0 15px;
    font-size: 16px;
    color: #fff;
  }
  .controls button {
    background: #444;
    border: 1px solid #666;
    border-radius: 4px;
    padding: 5px 15px;
    cursor: pointer;
  }
  .controls button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .fullscreen-btn {
    position: absolute;
    top: 15px;
    right: 15px;
    z-index: 100;
  }
`;

const convertJsonToMarkdownArray = (slides) => {
  if (!Array.isArray(slides)) return [];
  return slides.map(slide => {
    let markdown = '';
    if (slide.title) markdown += `# ${slide.title}\n\n`;
    if (slide.content) markdown += `${slide.content.replace(/\n/g, '\n\n')}`;
    return markdown;
  });
};

// Fallback: try to extract a JSON array from arbitrary text (code fences, prefixes, etc.)
const extractJsonArrayClient = (text) => {
  if (!text) return null;
  const t = String(text).trim();
  // 1) direct parse
  try {
    const d = JSON.parse(t);
    if (Array.isArray(d)) return d;
    if (d && Array.isArray(d.slides)) return d.slides;
  } catch {}
  // 2) code fence
  const fenceMatch = t.match(/```(?:json)?\n([\s\S]*?)\n```/i);
  if (fenceMatch) {
    try {
      const d = JSON.parse(fenceMatch[1]);
      if (Array.isArray(d)) return d;
      if (d && Array.isArray(d.slides)) return d.slides;
    } catch {}
  }
  // 3) first bracket block (greedy to include nested) – find first '[' and last ']'
  const first = t.indexOf('[');
  const last = t.lastIndexOf(']');
  if (first !== -1 && last !== -1 && last > first) {
    const candidate = t.slice(first, last + 1);
    try {
      const d = JSON.parse(candidate);
      if (Array.isArray(d)) return d;
    } catch {}
  }
  return null;
};

const SlidePreview = (props) => {
  // Chainlit CustomElement passes props object as-is. Read directly.
  const { slides_json = '[]', title = 'Slide Preview' } = props || {};
  const [currentPage, setCurrentPage] = useState(1);
  const [librariesLoaded, setLibrariesLoaded] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    // Use Marked (UMD) to avoid ESM/global issues
    loadScript('https://cdn.jsdelivr.net/npm/marked/marked.min.js')
      .then(() => setLibrariesLoaded(true))
      .catch(error => console.error('Failed to load marked:', error));
  }, []);

  const slides = useMemo(() => {
    try {
      let data = [];
      const sj = slides_json;
      // Debug visibility (use console.log so it appears at default level)
      try { console.log('[SlidePreview] slides_json type:', typeof sj); } catch (_) {}
      if (Array.isArray(sj)) {
        data = sj;
      } else if (typeof sj === 'string') {
        const parsed = JSON.parse(sj);
        if (Array.isArray(parsed)) data = parsed;
        else if (parsed && Array.isArray(parsed.slides)) data = parsed.slides;
      } else if (sj && typeof sj === 'object') {
        if (Array.isArray(sj.slides)) data = sj.slides;
      }
      // If still empty, try robust client-side extraction from raw string
      if ((!data || data.length === 0) && typeof sj === 'string') {
        const extracted = extractJsonArrayClient(sj);
        if (Array.isArray(extracted)) data = extracted;
      }
      try { console.log('[SlidePreview] parsed slides length:', Array.isArray(data) ? data.length : 'N/A'); } catch (_) {}
      return convertJsonToMarkdownArray(data);
    } catch (e) {
      console.error('Failed to parse slides_json:', e);
      return ['Error: Invalid slide data format.'];
    }
  }, [slides_json]);

  const totalPages = slides.length;

  const toggleFullScreen = () => {
    const elem = containerRef.current;
    if (!elem) return;
    if (!document.fullscreenElement) {
      elem.requestFullscreen().catch(err => alert(`Fullscreen error: ${err.message}`));
    } else {
      document.exitFullscreen();
    }
  };

  if (!librariesLoaded) {
    return <div>Loading Markdown renderer...</div>;
  }

  if (!slides_json || totalPages === 0) {
    const preview = typeof slides_json === 'string' ? slides_json.slice(0, 500) : JSON.stringify(slides_json).slice(0, 500);
    return (
      <div>
        <div>Loading slides or no slides to display...</div>
        <details style={{ marginTop: 12 }}>
          <summary>Debug: slides_json preview</summary>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{preview}</pre>
        </details>
      </div>
    );
  }

  return (
    <div className="slide-preview-container" ref={containerRef}>
      <style>{styles}</style>
      {/* On-screen debug banner */}
      <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>
        <span>Debug: slides_json type = {typeof slides_json}; pages = {totalPages}</span>
      </div>
      <div className="slide-render-area">
        <div className="slide-content">
          {librariesLoaded && window.marked ? (
            <div dangerouslySetInnerHTML={{ __html: window.marked.parse(slides[currentPage - 1] || '') }} />
          ) : (
            <div>Loading Markdown renderer...</div>
          )}
        </div>
      </div>
      <div className="controls">
        <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1}>Prev</button>
        <span>Page {currentPage} of {totalPages}</span>
        <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages}>Next</button>
      </div>
      <button onClick={toggleFullScreen} className="fullscreen-btn">Fullscreen</button>
    </div>
  );
};

export default SlidePreview;

