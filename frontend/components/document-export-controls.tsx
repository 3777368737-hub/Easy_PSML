"use client";

import { useId, useState } from "react";
import Icon from "@/components/icon";
import { apiDownloadFetch, readableError } from "@/lib/api";

type ExportFormat = "docx" | "pdf";

type DocumentExportControlsProps = {
  endpoint: string;
  artifactVersionId?: string;
  disabled?: boolean;
};

function saveDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function DocumentExportControls({
  endpoint,
  artifactVersionId,
  disabled = false,
}: DocumentExportControlsProps) {
  const formatLabelId = useId();
  const statusId = useId();
  const [format, setFormat] = useState<ExportFormat>("docx");
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [message, setMessage] = useState("");
  const [messageIsError, setMessageIsError] = useState(false);

  async function exportDraft() {
    if (exporting || disabled) return;
    setExporting(format);
    setMessage("");
    setMessageIsError(false);
    try {
      const result = await apiDownloadFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          format,
          artifact_version_id: artifactVersionId || undefined,
        }),
      });
      if (!result.blob.size) {
        throw new Error("生成的文件为空，请重试。");
      }
      saveDownload(
        result.blob,
        result.filename || `GradPilot-essay.${format}`,
      );
      setMessage(
        result.formatting === "fallback"
          ? `已生成 ${format.toUpperCase()} 文件。模型服务当前不可用或尚未开通，本次已使用标准排版。`
          : `GLM 排版完成，${format.toUpperCase()} 文件已开始下载。`,
      );
    } catch (err) {
      setMessageIsError(true);
      setMessage(readableError(err, "生成文书文件失败，请重试。"));
    } finally {
      setExporting(null);
    }
  }

  const controlsDisabled = disabled || Boolean(exporting);

  return (
    <section className="document-export" aria-labelledby={formatLabelId}>
      <div className="export-format-group">
        <span id={formatLabelId} className="export-label">
          文件格式
        </span>
        <div className="export-format-options" role="radiogroup">
          {(["docx", "pdf"] as const).map((option) => (
            <label
              key={option}
              className={`export-format-option ${
                format === option ? "is-selected" : ""
              }`}
            >
              <input
                type="radio"
                name={`document-export-format-${formatLabelId}`}
                value={option}
                checked={format === option}
                disabled={controlsDisabled}
                onChange={() => {
                  setFormat(option);
                  setMessage("");
                }}
              />
              <span>{option === "docx" ? "DOCX" : "PDF"}</span>
            </label>
          ))}
        </div>
      </div>

      <button
        className="btn export-submit"
        type="button"
        data-agent-capability="essay.download"
        disabled={controlsDisabled}
        aria-describedby={statusId}
        onClick={() => void exportDraft()}
      >
        <Icon name={exporting ? "clock" : "download"} size={17} />
        {exporting ? `正在生成 ${exporting.toUpperCase()}` : "生成并下载"}
      </button>

      <div id={statusId} className="export-feedback" aria-live="polite">
        {exporting ? (
          <>
            <div
              className="export-progress"
              role="progressbar"
              aria-label="正在生成文书文件"
              aria-valuetext={`正在生成 ${exporting.toUpperCase()} 文件`}
            >
              <span />
            </div>
            <p className="export-wait">
              GLM 正在整理文书并生成 {exporting.toUpperCase()} 文件，请稍候。
            </p>
          </>
        ) : null}
        {message ? (
          <p
            className={`export-message ${messageIsError ? "is-error" : "is-success"}`}
            role={messageIsError ? "alert" : undefined}
          >
            {message}
          </p>
        ) : null}
      </div>
    </section>
  );
}
