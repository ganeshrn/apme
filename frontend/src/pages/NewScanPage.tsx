import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useScanStream,
  type ProgressEntry,
  type ScanStatus,
} from "../hooks/useScanStream";

type TabId = "upload" | "project";

export function NewScanPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabId>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [ansibleVersion, setAnsibleVersion] = useState("");
  const [collections, setCollections] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);

  const { status, progress, result, error, startScan, cancel, reset } =
    useScanStream();

  useEffect(() => {
    if (result) {
      const timer = setTimeout(
        () => navigate(`/scans/${result.scan_id}`),
        1500,
      );
      return () => clearTimeout(timer);
    }
  }, [result, navigate]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (status !== "idle") return;
      const dropped = Array.from(e.dataTransfer.files);
      setFiles((prev) => [...prev, ...dropped]);
    },
    [status],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!e.target.files) return;
      setFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
      e.target.value = "";
    },
    [],
  );

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleSubmit = useCallback(() => {
    if (files.length === 0) return;
    startScan(files, { ansibleVersion, collections });
  }, [files, ansibleVersion, collections, startScan]);

  const handleReset = useCallback(() => {
    reset();
    setFiles([]);
  }, [reset]);

  const isRunning = status === "uploading" || status === "scanning";

  return (
    <>
      <header className="apme-page-header">
        <h1 className="apme-page-title">New Scan</h1>
      </header>

      <div className="apme-tabs">
        <button
          className={`apme-tab ${activeTab === "upload" ? "active" : ""}`}
          onClick={() => setActiveTab("upload")}
          disabled={isRunning}
        >
          Upload Files
        </button>
        <button
          className="apme-tab disabled"
          title="Coming soon — SCM/project mode"
          disabled
        >
          Project (SCM)
        </button>
      </div>

      {activeTab === "upload" && status === "idle" && (
        <div className="apme-scan-form">
          <div
            className={`apme-drop-zone ${isDragOver ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="apme-drop-icon">+</div>
            <div className="apme-drop-text">
              Drop Ansible files here or click to browse
            </div>
            <div className="apme-drop-hint">
              Supports individual files or entire directories
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".yml,.yaml,.json,.j2,.jinja2,.cfg,.ini,.toml,.py,.sh"
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
          </div>

          <div style={{ marginTop: 8 }}>
            <button
              className="apme-btn-secondary"
              onClick={() => dirInputRef.current?.click()}
            >
              Select Directory
            </button>
            <input
              ref={dirInputRef}
              type="file"
              /* @ts-expect-error webkitdirectory is non-standard */
              webkitdirectory=""
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
          </div>

          {files.length > 0 && (
            <div className="apme-file-list">
              <h3>
                {files.length} file{files.length !== 1 ? "s" : ""} selected
              </h3>
              <ul>
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="apme-file-item">
                    <span className="apme-file-name">
                      {(f as File & { webkitRelativePath?: string })
                        .webkitRelativePath || f.name}
                    </span>
                    <span className="apme-file-size">
                      {(f.size / 1024).toFixed(1)} KB
                    </span>
                    <button
                      className="apme-file-remove"
                      onClick={() => removeFile(i)}
                    >
                      x
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <details className="apme-options-panel">
            <summary>Advanced Options</summary>
            <div className="apme-form-group">
              <label htmlFor="ansible-version">Ansible Core Version</label>
              <input
                id="ansible-version"
                type="text"
                placeholder="e.g. 2.16"
                value={ansibleVersion}
                onChange={(e) => setAnsibleVersion(e.target.value)}
              />
            </div>
            <div className="apme-form-group">
              <label htmlFor="collections">Collections (comma-separated)</label>
              <input
                id="collections"
                type="text"
                placeholder="e.g. ansible.posix, community.general"
                value={collections}
                onChange={(e) => setCollections(e.target.value)}
              />
            </div>
          </details>

          <button
            className="apme-btn-primary"
            disabled={files.length === 0}
            onClick={handleSubmit}
          >
            Start Scan
          </button>
        </div>
      )}

      {isRunning && <ScanProgress status={status} progress={progress} onCancel={cancel} />}

      {status === "done" && result && (
        <div className="apme-scan-complete">
          <div className="apme-complete-icon">&#10003;</div>
          <h2>Scan Complete</h2>
          <p>
            Found <strong>{result.total_violations}</strong> violation
            {result.total_violations !== 1 ? "s" : ""}
          </p>
          <p className="apme-redirect-hint">
            Redirecting to results...
          </p>
        </div>
      )}

      {status === "error" && (
        <div className="apme-scan-error">
          <h2>Scan Failed</h2>
          <p className="apme-error-message">{error}</p>
          <button className="apme-btn-primary" onClick={handleReset}>
            Try Again
          </button>
        </div>
      )}
    </>
  );
}

function ScanProgress({
  status,
  progress,
  onCancel,
}: {
  status: ScanStatus;
  progress: ProgressEntry[];
  onCancel: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [progress.length]);

  return (
    <div className="apme-scan-progress">
      <div className="apme-progress-header">
        <h2>
          {status === "uploading" ? "Uploading files..." : "Scanning..."}
        </h2>
        <button className="apme-btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="apme-spinner" />

      <div className="apme-timeline">
        {progress.map((entry, i) => (
          <div key={i} className="apme-timeline-entry">
            <span className="apme-timeline-phase">{entry.phase}</span>
            <span className="apme-timeline-message">{entry.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
