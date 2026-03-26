import { Tooltip } from "antd";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AgentContextUsage } from "../../../api/types";
import styles from "./contextUsageRing.module.less";

type ContextUsageRingProps = {
  usage: AgentContextUsage | null;
  loading?: boolean;
  theme?: "default" | "azure";
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function getProgressColor(progress: number): string {
  const hue = clamp((1 - progress) * 120, 0, 120);
  return `hsl(${hue}, 72%, 48%)`;
}

function formatCompactK(value: number): string {
  const compact = value / 1000;
  const digits = compact >= 10 ? 0 : 1;
  return `${compact.toFixed(digits)}k`;
}

function formatKValue(value: number): string {
  const compact = value / 1000;
  const digits = compact >= 10 ? 0 : 1;
  return compact.toFixed(digits);
}

function formatTooltipLine(label: string, value: number): string {
  return `${label} ${formatCompactK(value)}`;
}

export default function ContextUsageRing({
  usage,
  loading = false,
  theme = "default",
}: ContextUsageRingProps) {
  const badgeRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const progress = clamp(usage?.usage_ratio ?? 0, 0, 1);
  const threshold = clamp(usage?.compact_threshold_ratio ?? 0, 0, 1);
  const radius = 20;
  const circumference = 2 * Math.PI * radius;
  const progressLength = circumference * progress;
  const markerAngle = threshold * Math.PI * 2;
  const markerInner = 16.6;
  const markerOuter = 24;
  const markerX1 = 28 + Math.cos(markerAngle) * markerInner;
  const markerY1 = 28 + Math.sin(markerAngle) * markerInner;
  const markerX2 = 28 + Math.cos(markerAngle) * markerOuter;
  const markerY2 = 28 + Math.sin(markerAngle) * markerOuter;
  const usagePercent = Math.round(progress * 100);
  const progressColor = getProgressColor(progress);
  const tooltipColor = theme === "azure" ? "#edf5fb" : "#eef6ef";
  const tooltipToneClassName =
    theme === "azure"
      ? styles.contextUsageTooltipAzure
      : styles.contextUsageTooltipDefault;
  const usageSummary = usage
    ? `${formatKValue(usage.used_tokens)}/${formatKValue(usage.max_input_tokens)} K`
    : "";

  useLayoutEffect(() => {
    const badge = badgeRef.current;
    const container = badge?.parentElement;
    if (!badge || !container) return;

    let frameId = 0;
    let wrapperObserver: ResizeObserver | null = null;

    const updatePosition = () => {
      const inputWrapper = container.querySelector<HTMLElement>(
        '[class*="chat-anywhere-input-wrapper"]',
      );
      if (!inputWrapper) return;

      const containerRect = container.getBoundingClientRect();
      const wrapperRect = inputWrapper.getBoundingClientRect();
      const badgeSize = badge.getBoundingClientRect().width || 32;
      const gap = 2;
      const lift = 4;
      const boundaryInset = 6;
      const wrapperRight = wrapperRect.right - containerRect.left;
      const wrapperBottom = wrapperRect.bottom - containerRect.top;
      const preferredOutsideLeft = Math.round(wrapperRight + gap);
      const maxLeft = Math.round(containerRect.width - badgeSize - boundaryInset);
      const insideLeft = Math.round(wrapperRight - badgeSize - 4);
      const resolvedLeft =
        preferredOutsideLeft <= maxLeft
          ? preferredOutsideLeft
          : clamp(insideLeft, boundaryInset, maxLeft);

      setPosition({
        left: resolvedLeft,
        top: Math.round(wrapperBottom - badgeSize - lift),
      });

      if (!wrapperObserver) {
        wrapperObserver = new ResizeObserver(() => {
          cancelAnimationFrame(frameId);
          frameId = requestAnimationFrame(updatePosition);
        });
        wrapperObserver.observe(inputWrapper);
      }
    };

    const scheduleUpdate = () => {
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(updatePosition);
    };

    scheduleUpdate();

    const containerObserver = new ResizeObserver(scheduleUpdate);
    const mutationObserver = new MutationObserver(scheduleUpdate);
    containerObserver.observe(container);
    mutationObserver.observe(container, { childList: true, subtree: true, attributes: true });
    window.addEventListener("resize", scheduleUpdate);

    return () => {
      cancelAnimationFrame(frameId);
      wrapperObserver?.disconnect();
      containerObserver.disconnect();
      mutationObserver.disconnect();
      window.removeEventListener("resize", scheduleUpdate);
    };
  }, []);

  const tooltipOverlayClassName = useMemo(
    () =>
      `${styles.contextUsageTooltipOverlay} ${
        theme === "azure"
          ? styles.contextUsageTooltipOverlayAzure
          : styles.contextUsageTooltipOverlayDefault
      }`,
    [theme],
  );

  const tooltipContent = usage ? (
    <div className={`${styles.contextUsageTooltip} ${tooltipToneClassName}`}>
      <div className={styles.contextUsageTooltipTitle}>背景信息窗口：</div>
      <div className={styles.contextUsageTooltipSubtitle}>{usagePercent}% 已用</div>
      <div className={styles.contextUsageTooltipUsage}>{usageSummary}</div>
      <div>{formatTooltipLine("压缩阈值", usage.compact_threshold_tokens)}</div>
      <div>{formatTooltipLine("保留阈值", usage.reserve_threshold_tokens)}</div>
    </div>
  ) : (
    <div className={`${styles.contextUsageTooltip} ${tooltipToneClassName}`}>
      <div className={styles.contextUsageTooltipTitle}>背景信息窗口：</div>
      <div>上下文统计暂不可用</div>
    </div>
  );

  return (
    <Tooltip
      title={tooltipContent}
      placement="topRight"
      overlayClassName={tooltipOverlayClassName}
      color={tooltipColor}
    >
      <div
        ref={badgeRef}
        className={`${styles.contextUsageBadge}${loading ? ` ${styles.contextUsageBadgeLoading}` : ""}`}
        aria-label="当前会话上下文占用"
        style={
          position
            ? {
                left: `${position.left}px`,
                top: `${position.top}px`,
              }
            : { opacity: 0 }
        }
      >
        <svg
          className={styles.contextUsageSvg}
          viewBox="0 0 56 56"
          role="img"
          aria-hidden="true"
        >
          <circle
            className={styles.contextUsageTrack}
            cx="28"
            cy="28"
            r={radius}
            fill="none"
          />
          <circle
            className={styles.contextUsageProgress}
            cx="28"
            cy="28"
            r={radius}
            fill="none"
            style={{
              stroke: progressColor,
              strokeDasharray: `${progressLength} ${circumference - progressLength}`,
            }}
          />
          <line
            className={styles.contextUsageMarker}
            x1={markerX1}
            y1={markerY1}
            x2={markerX2}
            y2={markerY2}
          />
        </svg>
      </div>
    </Tooltip>
  );
}
