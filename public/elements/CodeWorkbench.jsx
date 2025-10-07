import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  Suspense,
} from 'react';
//import { detectLanguage } from './languageGuesser.js';// 任意: 言語推定ユーティリティ（後述）
//import StatusBar from './StatusBar'; // 任意: ステータスバー用コンポーネント化も可

const EXTENSION_TO_LANGUAGE = {
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  sass: 'scss',
  js: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  json: 'json',
  md: 'markdown',
  py: 'python',
  rb: 'ruby',
  java: 'java',
  php: 'php',
  go: 'go',
  rs: 'rust',
  c: 'c',
  cpp: 'cpp',
  h: 'c',
  hpp: 'cpp',
  cs: 'csharp',
  sql: 'sql',
  yaml: 'yaml',
  yml: 'yaml',
};

function detectLanguage(filename = '', code = '') {
  const extensionMatch = filename.toLowerCase().match(/\.([a-z0-9]+)$/);
  if (extensionMatch) {
    const ext = extensionMatch[1];
    if (EXTENSION_TO_LANGUAGE[ext]) {
      return EXTENSION_TO_LANGUAGE[ext];
    }
  }

  const trimmed = (code || '').trimStart();

  if (trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')) {
    return 'html';
  }
  if (trimmed.startsWith('<svg')) {
    return 'xml';
  }
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return 'json';
  }
  if (/^\s*function\s|\s=>\s|const\s.+\s=/.test(trimmed)) {
    return 'javascript';
  }

  return undefined;
}



const MonacoEditor = React.lazy(() => import('@monaco-editor/react'));

const DEFAULT_HEIGHT = 420;
const DEFAULT_FILENAME = 'index.html';
const FALLBACK_LANGUAGE = 'html';

export default function CodeWorkbench(props) {
  const {
    code: initialCode = '',
    title = 'Canvas: Code Workbench',
    filename: propFilename,
    language: propLanguage,
    readOnly = false,
    autoPreview = true,
  } = props || {};

  const iframeRef = useRef(null);
  const editorRef = useRef(null);
  const containerRef = useRef(null);
  const fullscreenWrapperRef = useRef(null);

  const [editorCode, setEditorCode] = useState(initialCode);
  const [activeView, setActiveView] = useState(autoPreview ? 'split' : 'editor'); // 'editor' | 'preview' | 'split'
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [filename, setFilename] = useState(propFilename || DEFAULT_FILENAME);
  const [language, setLanguage] = useState(
    propLanguage || detectLanguage(propFilename, initialCode) || FALLBACK_LANGUAGE,
  );
  const [cursorPos, setCursorPos] = useState({ lineNumber: 1, column: 1 });
  const [statusText, setStatusText] = useState('Ready');

  /* ---------- 初期コード変化を監視 ---------- */
  useEffect(() => {
    setEditorCode(initialCode);
  }, [initialCode]);

  useEffect(() => {
    if (propFilename && propFilename !== filename) {
      setFilename(propFilename);
    }
  }, [propFilename, filename]);

  useEffect(() => {
    if (propLanguage && propLanguage !== language) {
      setLanguage(propLanguage);
    }
  }, [propLanguage, language]);

  /* ---------- 全画面切り替えイベント ---------- */
  useEffect(() => {
    const listener = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', listener);
    return () => document.removeEventListener('fullscreenchange', listener);
  }, []);

  const enterFullscreen = useCallback(() => {
    if (fullscreenWrapperRef.current) {
      fullscreenWrapperRef.current.requestFullscreen();
    }
  }, []);

  const exitFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    }
  }, []);

  /* ---------- プレビュー更新 ---------- */
  const updatePreview = useCallback(
    (code = editorCode) => {
      if (!iframeRef.current) return;
      iframeRef.current.srcdoc = code;
      setStatusText(`Preview updated at ${new Date().toLocaleTimeString()}`);
    },
    [editorCode],
  );

  useEffect(() => {
    if (autoPreview && (activeView === 'preview' || activeView === 'split')) {
      const timeout = setTimeout(() => updatePreview(editorCode), 150);
      return () => clearTimeout(timeout);
    }
  }, [activeView, autoPreview, editorCode, updatePreview]);

  /* ---------- ダウンロード ---------- */
  const handleDownload = useCallback(() => {
    const blob = new Blob([editorCode], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename || DEFAULT_FILENAME;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1200);
    setStatusText(`Downloaded ${filename}`);
  }, [editorCode, filename]);

  /* ---------- Monaco Editor onMount ---------- */
  const handleEditorMount = useCallback((editor, monaco) => {
    editorRef.current = editor;

    // 行番号・カーソル位置をステータスバーへ反映
    const cursorListener = editor.onDidChangeCursorPosition((ev) => {
      setCursorPos({ lineNumber: ev.position.lineNumber, column: ev.position.column });
    });

    // Ctrl/Cmd + Enter → プレビュー更新
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      updatePreview(editor.getValue());
      setActiveView((view) => (view === 'editor' ? 'preview' : view));
    });

    // Ctrl/Cmd + S → ダウンロード or 保存（必要に応じて API 呼び出し）
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, (ev) => {
      ev.preventDefault();
      handleDownload();
    });

    // Prop から readOnly を反映
    editor.updateOptions({ readOnly, minimap: { enabled: true }, automaticLayout: true });

    // 言語をセット（モジュール読み込み後に解析した結果）
    if (language) {
      monaco.editor.setModelLanguage(editor.getModel(), language);
    }

    return () => {
      cursorListener && cursorListener.dispose();
    };
  }, [handleDownload, language, readOnly, updatePreview]);

  const editorOptions = useMemo(
    () => ({
      fontSize: 13,
      wordWrap: 'on',
      scrollBeyondLastLine: false,
      tabSize: 2,
      insertSpaces: true,
      minimap: { enabled: true },
      smoothScrolling: true,
      renderWhitespace: 'selection',
      automaticLayout: true,
      readOnly,
    }),
    [readOnly],
  );

  /* ---------- テーマ切り替え（システム設定に従う） ---------- */
  const prefersDarkMode = useMemo(
    () => window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches,
    [],
  );
  const [theme, setTheme] = useState(prefersDarkMode ? 'vs-dark' : 'vs');
  useEffect(() => {
    if (!window.matchMedia) return;
    const matcher = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = (e) => setTheme(e.matches ? 'vs-dark' : 'vs');
    matcher.addEventListener('change', listener);
    return () => matcher.removeEventListener('change', listener);
  }, []);

  /* ---------- レイアウト ---------- */
  const renderToolbar = () => (
    <div style={styles.toolbar}>
      <div style={styles.leftGroup}>
        <span style={styles.title}>{title}</span>
        <span style={styles.filename}>{filename}</span>
        <span style={styles.language}>{language}</span>
      </div>
      <div style={styles.centerGroup}>
        <button
          type="button"
          style={activeView === 'editor' ? styles.tabActive : styles.tab}
          onClick={() => setActiveView('editor')}
        >
          Editor
        </button>
        <button
          type="button"
          style={activeView === 'preview' ? styles.tabActive : styles.tab}
          onClick={() => {
            setActiveView('preview');
            updatePreview(editorCode);
          }}
        >
          Preview
        </button>
        <button
          type="button"
          style={activeView === 'split' ? styles.tabActive : styles.tab}
          onClick={() => {
            setActiveView('split');
            updatePreview(editorCode);
          }}
        >
          Split
        </button>
      </div>
      <div style={styles.rightGroup}>
        {activeView !== 'editor' && (
          <button type="button" style={styles.controlBtn} onClick={enterFullscreen}>
            Fullscreen
          </button>
        )}
        <button type="button" style={styles.controlBtn} onClick={() => updatePreview(editorCode)}>
          Refresh
        </button>
        <button type="button" style={styles.controlBtn} onClick={handleDownload}>
          Download
        </button>
      </div>
    </div>
  );

  const renderPreview = () => (
    <div ref={fullscreenWrapperRef} style={styles.previewWrapper}>
      <iframe
        ref={iframeRef}
        style={styles.iframe}
        sandbox="allow-scripts allow-same-origin"
        title="Code Preview"
      />
      {isFullscreen && (
        <button type="button" style={styles.exitFullscreenBtn} onClick={exitFullscreen}>
          Exit Fullscreen
        </button>
      )}
    </div>
  );

  return (
    <div ref={containerRef} style={styles.container}>
      {renderToolbar()}
      <div style={styles.body(activeView)}>
        {(activeView === 'editor' || activeView === 'split') && (
          <div style={styles.editorPane(activeView)}>
            <Suspense fallback={<textarea style={styles.fallbackTextarea} defaultValue={editorCode} readOnly />}>
              <MonacoEditor
                height={DEFAULT_HEIGHT}
                value={editorCode}
                onChange={(value) => setEditorCode(value ?? '')}
                onMount={handleEditorMount}
                theme={theme}
                defaultLanguage={language}
                options={editorOptions}
              />
            </Suspense>
          </div>
        )}
        {(activeView === 'preview' || activeView === 'split') && (
          <div style={styles.previewPane(activeView)}>{renderPreview()}</div>
        )}
      </div>

    </div>
  );
}

/* ---------- スタイル群 ---------- */
const styles = {
  container: {
    border: '1px solid #e5e7eb',
    borderRadius: 8,
    overflow: 'hidden',
    background: '#fff',
    display: 'flex',
    flexDirection: 'column',
    minHeight: DEFAULT_HEIGHT + 48,
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    padding: '8px 12px',
    borderBottom: '1px solid #e5e7eb',
    gap: 12,
  },
  leftGroup: { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 },
  centerGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginLeft: 'auto',
    marginRight: 'auto',
  },
  rightGroup: { display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' },
  title: { fontSize: 13, fontWeight: 600, color: '#111827' },
  filename: { fontSize: 12, color: '#4b5563' },
  language: {
    padding: '2px 6px',
    borderRadius: 4,
    background: '#ede9fe',
    color: '#5b21b6',
    fontSize: 11,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  },
  tab: {
    padding: '6px 12px',
    borderRadius: 6,
    border: '1px solid transparent',
    background: '#f3f4f6',
    cursor: 'pointer',
  },
  tabActive: {
    padding: '6px 12px',
    borderRadius: 6,
    border: '1px solid #818cf8',
    background: '#e0e7ff',
    color: '#3730a3',
    cursor: 'pointer',
  },
  controlBtn: {
    padding: '6px 12px',
    background: '#111827',
    color: '#fff',
    border: '1px solid #111827',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 12,
  },
  body: (view) => ({
    display: 'flex',
    flex: 1,
    minHeight: DEFAULT_HEIGHT,
    flexDirection: view === 'split' ? 'row' : 'column',
  }),
  editorPane: (view) => ({
    flex: view === 'split' ? 1 : undefined,
    width: view === 'split' ? '50%' : '100%',
    height: view === 'split' ? '100%' : DEFAULT_HEIGHT,
  }),
  previewPane: (view) => ({
    flex: view === 'split' ? 1 : undefined,
    width: view === 'split' ? '50%' : '100%',
    height: view === 'split' ? '100%' : DEFAULT_HEIGHT,
    borderLeft: view === 'split' ? '1px solid #e5e7eb' : 'none',
    position: 'relative',
  }),
  previewWrapper: { position: 'relative', width: '100%', height: '100%' },
  iframe: { width: '100%', height: '100%', border: 'none', background: '#fff' },
  exitFullscreenBtn: {
    position: 'fixed',
    top: '1rem',
    right: '1rem',
    padding: '8px 16px',
    background: 'rgba(17, 24, 39, 0.85)',
    color: '#fff',
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    zIndex: 2147483647,
  },
  fallbackTextarea: {
    width: '100%',
    height: DEFAULT_HEIGHT,
    border: 'none',
    outline: 'none',
    padding: 12,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    resize: 'none',
    background: '#f9fafb',
  },
};
