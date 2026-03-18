/**
 * 左下角 GridPaw 署名面板。
 * --- GridPaw: start ---
 */
import styles from "./index.module.less";

export default function GridPawCreditCard() {
  return (
    <div
      id="gridpaw-credit-card"
      className={styles.card}
      role="contentinfo"
      aria-label="GridPaw attribution"
    >
      <b>GridPaw</b> (Original by <b>agentscope-ai/CoPaw</b>)
      <br />
      Prod. by <b>Li Linxin</b> (feat. <b>Claude Opus 4.6</b> × <b>GLM 5</b>)
    </div>
  );
}
/** --- GridPaw: end --- */
