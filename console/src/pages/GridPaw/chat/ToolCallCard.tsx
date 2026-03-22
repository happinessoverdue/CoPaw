import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { ToolCall } from "@agentscope-ai/chat";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
import styles from "./toolCallCard.module.less";

type ToolCallCardProps = {
  title: string;
  input: unknown;
  output: unknown;
  loading?: boolean;
  defaultOpen?: boolean;
  extraContent?: ReactNode;
};

function parseMaybeJsonString(value: string): unknown {
  let current: unknown = value;
  for (let i = 0; i < 2; i += 1) {
    if (typeof current !== "string") break;
    const trimmed = current.trim();
    if (
      !trimmed ||
      !(
        (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
        (trimmed.startsWith("[") && trimmed.endsWith("]"))
      )
    ) {
      break;
    }
    try {
      current = JSON.parse(trimmed);
    } catch {
      break;
    }
  }
  return current;
}

function stringifyContent(value: unknown): string {
  if (typeof value === "string") {
    const parsed = parseMaybeJsonString(value);
    if (typeof parsed === "string") return value;
    try {
      return JSON.stringify(parsed, null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value ?? "", null, 2);
  } catch {
    return String(value ?? "");
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default function ToolCallCard(props: ToolCallCardProps) {
  const [viewerOpen, setViewerOpen] = useState(false);
  const [x, setX] = useState(140);
  const [y, setY] = useState(100);
  const [width, setWidth] = useState(760);
  const [height, setHeight] = useState(480);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeFrameRef = useRef<number | null>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const resizePointerIdRef = useRef<number | null>(null);
  const pendingRectRef = useRef<{ x: number; y: number; width: number; height: number } | null>(
    null,
  );
  const resizeRef = useRef<{
    direction: string;
    startX: number;
    startY: number;
    startW: number;
    startH: number;
    startLeft: number;
    startTop: number;
  } | null>(null);

  const inputText = useMemo(() => stringifyContent(props.input), [props.input]);
  const outputText = useMemo(() => stringifyContent(props.output), [props.output]);

  useEffect(() => {
    return () => {
      resizeCleanupRef.current?.();
    };
  }, []);

  const cleanupDocumentEvents = useCallback(() => {
    document.body.style.userSelect = "";
    window.onpointermove = null;
    window.onpointerup = null;
  }, []);

  const handleToolCardClickCapture = useCallback((event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as Element | null;
    if (!target) return;
    const isHeaderIconClick = !!target.closest('[class*="operate-card-header-icon"]');
    if (!isHeaderIconClick) return;
    event.preventDefault();
    event.stopPropagation();
    setViewerOpen(true);
  }, []);

  const handleDragStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!viewerOpen) return;
      dragRef.current = { dx: event.clientX - x, dy: event.clientY - y };
      document.body.style.userSelect = "none";
      window.onpointermove = (moveEvent: PointerEvent) => {
        const drag = dragRef.current;
        if (!drag) return;
        const maxX = Math.max(0, window.innerWidth - width - 12);
        const maxY = Math.max(0, window.innerHeight - height - 12);
        setX(clamp(moveEvent.clientX - drag.dx, 6, maxX));
        setY(clamp(moveEvent.clientY - drag.dy, 6, maxY));
      };
      window.onpointerup = () => {
        dragRef.current = null;
        cleanupDocumentEvents();
      };
    },
    [cleanupDocumentEvents, height, viewerOpen, width, x, y],
  );

  const handleResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, direction: string) => {
      event.stopPropagation();
      event.preventDefault();
      const handle = event.currentTarget;
      resizeRef.current = {
        direction,
        startX: event.clientX,
        startY: event.clientY,
        startW: width,
        startH: height,
        startLeft: x,
        startTop: y,
      };
      resizePointerIdRef.current = event.pointerId;
      handle.setPointerCapture?.(event.pointerId);
      document.body.style.userSelect = "none";

      const flushPendingResize = () => {
        const rect = pendingRectRef.current;
        if (!rect) return;
        setWidth(rect.width);
        setHeight(rect.height);
        setX(rect.x);
        setY(rect.y);
        resizeFrameRef.current = null;
      };

      const onMove = (moveEvent: PointerEvent) => {
        if (
          resizePointerIdRef.current !== null &&
          moveEvent.pointerId !== resizePointerIdRef.current
        ) {
          return;
        }
        const ref = resizeRef.current;
        if (!ref) return;
        const dx = moveEvent.clientX - ref.startX;
        const dy = moveEvent.clientY - ref.startY;
        const minW = 420;
        const minH = 260;
        const maxW = window.innerWidth - 12;
        const maxH = window.innerHeight - 12;
        let nextW = ref.startW;
        let nextH = ref.startH;
        let nextX = ref.startLeft;
        let nextY = ref.startTop;

        if (ref.direction.includes("e")) nextW = clamp(ref.startW + dx, minW, maxW);
        if (ref.direction.includes("s")) nextH = clamp(ref.startH + dy, minH, maxH);
        if (ref.direction.includes("w")) {
          const candidate = clamp(ref.startW - dx, minW, maxW);
          nextX = ref.startLeft + (ref.startW - candidate);
          nextW = candidate;
        }
        if (ref.direction.includes("n")) {
          const candidate = clamp(ref.startH - dy, minH, maxH);
          nextY = ref.startTop + (ref.startH - candidate);
          nextH = candidate;
        }

        pendingRectRef.current = {
          width: nextW,
          height: nextH,
          x: clamp(nextX, 6, window.innerWidth - nextW - 6),
          y: clamp(nextY, 6, window.innerHeight - nextH - 6),
        };

        if (resizeFrameRef.current === null) {
          resizeFrameRef.current = window.requestAnimationFrame(flushPendingResize);
        }
      };

      const endResize = () => {
        resizeRef.current = null;
        resizePointerIdRef.current = null;
        if (resizeFrameRef.current !== null) {
          window.cancelAnimationFrame(resizeFrameRef.current);
          flushPendingResize();
        }
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", endResize);
        window.removeEventListener("pointercancel", endResize);
        window.removeEventListener("blur", endResize);
        resizeCleanupRef.current = null;
        document.body.style.userSelect = "";
        try {
          if (handle.hasPointerCapture?.(event.pointerId)) {
            handle.releasePointerCapture(event.pointerId);
          }
        } catch {
          // ignore
        }
      };
      resizeCleanupRef.current = endResize;
      window.addEventListener("pointermove", onMove, { passive: true });
      window.addEventListener("pointerup", endResize);
      window.addEventListener("pointercancel", endResize);
      window.addEventListener("blur", endResize);
    },
    [height, width, x, y],
  );

  return (
    <>
      <div onClickCapture={handleToolCardClickCapture} style={{ width: "100%" }}>
        <ToolCall
          loading={props.loading}
          defaultOpen={props.defaultOpen ?? false}
          title={props.title}
          input={props.input as string | Record<string, unknown>}
          output={props.output as string | Record<string, unknown>}
        />
        {props.extraContent}
      </div>

      {viewerOpen &&
        createPortal(
          <div
            className={styles.viewerCard}
            style={{ left: x, top: y, width, height }}
          >
            <div className={styles.viewerHeader} onPointerDown={handleDragStart}>
              <div className={styles.viewerTitle}>{props.title}</div>
              <button
                type="button"
                className={styles.viewerClose}
                onClick={() => setViewerOpen(false)}
                title="关闭"
              >
                <X size={14} />
              </button>
            </div>
            <div className={styles.viewerBody}>
              <section className={styles.viewerPane}>
                <h4>输入</h4>
                <pre>{inputText}</pre>
              </section>
              <section className={styles.viewerPane}>
                <h4>输出</h4>
                <pre>{outputText}</pre>
              </section>
            </div>
            {["n", "s", "e", "w", "ne", "nw", "se", "sw"].map((direction) => (
              <div
                key={direction}
                className={`${styles.resizeHandle} ${styles[`resize${direction.toUpperCase()}`]}`}
                onPointerDown={(event) => handleResizeStart(event, direction)}
              />
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
