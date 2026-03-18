/**
 * 多租户模式下显示的租户身份卡片。fixed 于左上角，显示在 logo 上方，侧边栏收起时仍可见。
 * 调用 /auth/whoami 获取当前用户信息；非多租户环境（接口不存在）时自动隐藏。
 * --- GridPaw: start ---
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

interface WhoAmIResponse {
  logged_in: boolean;
  user_id?: string;
  user_name?: string;
  instance?: string;
}

export default function TenantUserCard() {
  const { t } = useTranslation();
  const [data, setData] = useState<WhoAmIResponse | null>(null);

  useEffect(() => {
    fetch("/auth/whoami")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("not found"))))
      .then((d: WhoAmIResponse) => {
        if (d?.logged_in) {
          setData(d);
          document.body.setAttribute("data-gridpaw-tenant-panel", "visible");
        }
      })
      .catch(() => {});
    return () => {
      document.body.removeAttribute("data-gridpaw-tenant-panel");
    };
  }, []);

  if (!data?.logged_in) return null;

  return (
    <div className={styles.card} role="region" aria-label={t("tenantUserCard.ariaLabel", "租户身份")}>
      <div className={styles.info}>
        <div className={styles.nameRow}>
          <span className={styles.userName}>{data.user_name || data.user_id || "-"}</span>
          <span className={styles.userId}>{data.user_id || ""}</span>
        </div>
        <div className={styles.instance} title={data.instance || ""}>
          {data.instance || "-"}
        </div>
      </div>
      <a href="/auth/logout" className={styles.logoutBtn}>
        {t("tenantUserCard.logout", "退出")}
      </a>
    </div>
  );
}
/** --- GridPaw: end --- */
