import { useEffect, useMemo, useState } from 'react';

export default function CodeWorkbench(props) {
  const { code: propCode, title = 'Canvas: Code Workbench' } = props || {};

  const [tab, setTab] = useState('editor'); // 'editor' | 'preview'
  const [editorCode, setEditorCode] = useState(propCode || '');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const iframeRef = React.useRef(null);
  const fullscreenWrapperRef = React.useRef(null);

  // When new code is passed from the backend, update the editor.
  useEffect(() => {
    setEditorCode(propCode || '');
  }, [propCode]);

  // When the preview tab is active, update the iframe content with the editor's code.
  useEffect(() => {
    if (tab === 'preview' && iframeRef.current) {
      iframeRef.current.srcdoc = editorCode;
    }
  }, [tab, editorCode]);

  const handleFullscreenChange = () => {
    if (document.fullscreenElement) {
      setIsFullscreen(true);
    } else {
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  const enterFullscreen = () => {
    if (fullscreenWrapperRef.current) {
      fullscreenWrapperRef.current.requestFullscreen();
    }
  };

  const exitFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    }
  };

  const tabs = (
    <div style={styles.tabBar}>
      <button type="button" style={tab === 'editor' ? styles.tabActive : styles.tab} onClick={() => setTab('editor')}>Editor</button>
      <button type="button" style={tab === 'preview' ? styles.tabActive : styles.tab} onClick={() => setTab('preview')}>Preview</button>
      <span style={styles.title}>{title}</span>
      <div style={{ flex: 1 }} />
      {tab === 'preview' && (
        <button type="button" style={styles.smallBtn} onClick={enterFullscreen}>Fullscreen</button>
      )}
      <button type="button" style={styles.smallBtn} onClick={() => download(editorCode, 'index.html')}>Download</button>
    </div>
  );

  return (
    <div style={styles.wrapper}>
      {tabs}
      {tab === 'editor' ? (
        <textarea
          style={styles.textarea}
          value={editorCode}
          onChange={(e) => setEditorCode(e.target.value)}
          spellCheck={false}
        />
      ) : (
        <div ref={fullscreenWrapperRef} style={styles.previewWrapper}>
          <iframe
            ref={iframeRef}
            style={styles.iframe}
            sandbox="allow-scripts allow-same-origin"
            title="JSX Preview"
          />
          {isFullscreen && (
            <button
              type="button"
              style={styles.closeFullscreenBtn}
              onClick={exitFullscreen}
            >
              Exit Fullscreen
            </button>
          )}
        </div>
      )}
    </div>
  );

}


const styles = {
  wrapper: { border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fff' },
  tabBar: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid #e5e7eb' },
  tab: { padding: '6px 12px', background: '#f3f4f6', border: '1px solid #e5e7eb', borderRadius: 6, cursor: 'pointer' },
  tabActive: { padding: '6px 12px', background: '#e0e7ff', border: '1px solid #c7d2fe', borderRadius: 6, cursor: 'pointer' },
  title: { marginLeft: 8, fontSize: 12, color: '#6b7280' },
  smallBtn: { padding: '6px 10px', background: '#111827', color: '#fff', border: '1px solid #111827', borderRadius: 6, cursor: 'pointer' },
  textarea: { width: '100%', height: 400, border: 'none', outline: 'none', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13, padding: 12, resize: 'vertical' },
  previewWrapper: { position: 'relative', width: '100%', height: 400, background: 'white' },
  iframe: { width: '100%', height: '100%', border: 'none' },
  closeFullscreenBtn: {
    position: 'fixed',
    top: '1rem',
    right: '1rem',
    padding: '8px 16px',
    background: 'rgba(0, 0, 0, 0.7)',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    zIndex: 2147483647,
  },
};

function download(text, filename) {
  const blob = new Blob([text], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
