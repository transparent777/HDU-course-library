"""正方教务系统 HTTP 客户端。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from hdu_killer.course.crypto import aes_encrypt_cas, rsa_encrypt_jw

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 90
CATALOG_TIMEOUT = 300


@dataclass
class BodyConfig:
    xkkz_id: dict[str, str] = field(default_factory=dict)
    ccdm: str = ""
    bh_id: str = ""
    jg_id: str = ""
    xsbj: str = ""
    xz: str = ""
    mzm: str = ""
    xslbdm: str = ""
    xbm: str = ""
    zyfx_id: str = ""
    xqh_id: str = ""


class JwClient:
    def __init__(self, user_agent: str = "") -> None:
        self.session = requests.Session()
        self.user_agent = user_agent or DEFAULT_UA
        self.body_config: BodyConfig | None = None
        self.njdm_id_xs: str = ""
        self.zyh_id_xs: str = ""

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent}

    def get(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        r = self.session.get(url, headers=self._headers(), timeout=timeout)
        r.raise_for_status()
        return r.text

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        r = self.session.post(url, data=data or {}, headers=self._headers(), timeout=timeout)
        r.raise_for_status()
        return r.text

    def post_with_retry(
        self,
        url: str,
        data: dict[str, str] | None = None,
        timeout: int = CATALOG_TIMEOUT,
        retries: int = 2,
    ) -> str:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self.post(url, data, timeout=timeout)
            except requests.exceptions.Timeout as e:
                last = e
                if attempt < retries:
                    time.sleep(3)
        raise last  # type: ignore[misc]

    def load_cookies(self, jsessionid: str, route: str) -> None:
        for c in (
            {"name": "JSESSIONID", "value": jsessionid, "domain": "newjw.hdu.edu.cn"},
            {"name": "route", "value": route, "domain": "newjw.hdu.edu.cn"},
        ):
            self.session.cookies.set(**c)

    def save_cookies(self, cfg: dict[str, Any]) -> None:
        for cookie in self.session.cookies:
            if cookie.name == "JSESSIONID":
                cfg["cookies"]["JSESSIONID"] = cookie.value
            if cookie.name == "route":
                cfg["cookies"]["route"] = cookie.value

    def get_csrftoken(self) -> str:
        html = self.get("https://newjw.hdu.edu.cn/jwglxt/xtgl/login_slogin.html")
        m = re.search(r'name="csrftoken"\s+value="([^"]+)"', html)
        if not m:
            raise RuntimeError("获取 csrftoken 失败")
        return m.group(1)

    def get_public_key(self) -> tuple[str, str]:
        url = f"https://newjw.hdu.edu.cn/jwglxt/xtgl/login_getPublicKey.html?time={int(time.time())}"
        data = json.loads(self.get(url))
        return data["modulus"], data.get("exponent", "010001")

    def newjw_login(self, username: str, password: str) -> None:
        token = self.get_csrftoken()
        mod, _ = self.get_public_key()
        enc_pwd = rsa_encrypt_jw(mod, password)
        body = self.post(
            "https://newjw.hdu.edu.cn/jwglxt/xtgl/login_slogin.html",
            {"csrftoken": token, "yhm": username, "mm": enc_pwd},
        )
        if "用户名或密码不正确" in body:
            raise RuntimeError("教务用户名或密码不正确")

    def get_cas_login_config(self) -> tuple[str, str]:
        html = self.get("https://sso.hdu.edu.cn/login")
        soup = BeautifulSoup(html, "html.parser")
        execution = soup.find("input", {"name": "execution"})
        croypto = soup.find("input", {"name": "croypto"})
        if not execution or not croypto:
            raise RuntimeError("获取 CAS 登录参数失败")
        return execution.get("value", ""), croypto.get("value", "")

    def cas_login_password(self, username: str, password: str) -> None:
        execution, croypto = self.get_cas_login_config()
        enc = aes_encrypt_cas(croypto, password)
        body = self.post(
            "https://sso.hdu.edu.cn/login",
            {
                "username": username,
                "type": "UsernamePassword",
                "_eventId": "submit",
                "geolocation": "",
                "execution": execution,
                "captcha_code": "",
                "croypto": croypto,
                "password": enc,
            },
        )
        if "统一身份认证" in body and "cas" in body.lower():
            raise RuntimeError("CAS 用户名或密码不正确")

    def cas_login_newjw(self) -> str:
        url = "https://sso.hdu.edu.cn/login?service=http://newjw.hdu.edu.cn/sso/driot4login"
        return self.get(url)

    def login_flow(self, cfg: dict[str, Any]) -> None:
        cookies = cfg.get("cookies", {})
        if cookies.get("enabled") == "1" and cookies.get("JSESSIONID") and cookies.get("route"):
            self.load_cookies(cookies["JSESSIONID"], cookies["route"])
            try:
                self.fetch_body_config()
                return
            except RuntimeError as e:
                if "登录过期" not in str(e):
                    raise

        cas = cfg.get("cas_login", {})
        nj = cfg.get("newjw_login", {})
        cas_level = int(cas.get("level", "0"))
        nj_level = int(nj.get("level", "1"))

        def try_cas() -> None:
            if cas.get("dingDingQrLoginEnabled") == "1":
                raise RuntimeError("钉钉扫码登录暂不支持，请使用学号密码登录")
            self.cas_login_password(cas["username"], cas["password"])
            page = self.cas_login_newjw()
            if "杭州电子科技大学本科教学管理服务平台" not in page:
                raise RuntimeError("CAS 登录教务失败")

        def try_nj() -> None:
            self.newjw_login(nj["username"], nj["password"])

        if cas_level < nj_level:
            try:
                try_cas()
            except RuntimeError:
                self.session.cookies.clear()
                try_nj()
        else:
            try:
                try_nj()
            except RuntimeError:
                self.session.cookies.clear()
                try_cas()

        self.save_cookies(cfg)

    def fetch_stu_info(self, cfg: dict[str, Any]) -> None:
        xn = cfg["time"]["XueNian"]
        xq = cfg["time"]["XueQi"]
        xqm = "3" if xq == "1" else "12" if xq == "2" else ""
        if not xqm:
            raise ValueError("学期格式错误")
        url = (
            "https://newjw.hdu.edu.cn/jwglxt/kbcx/xskbcx_cxXsgrkb.html"
            f"?gnmkdm=N2151&xnm={xn}&xqm={xqm}"
        )
        text = self.get(url)
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        data = json.loads(text)
        xs = data.get("xsxx") or {}
        if not xs.get("NJDM_ID") or not xs.get("ZYH_ID"):
            raise RuntimeError("获取学生信息失败")
        self.njdm_id_xs = xs["NJDM_ID"]
        self.zyh_id_xs = xs["ZYH_ID"]

    def fetch_body_config(self) -> BodyConfig:
        url = "https://newjw.hdu.edu.cn/jwglxt/xsxk/zzxkyzb_cxZzxkYzbIndex.html?gnmkdm=N253512&layout=default"
        html = self.get(url)
        if "统一身份认证" in html:
            raise RuntimeError("可能登录过期")
        if "对不起，当前不属于选课阶段" in html:
            raise RuntimeError("当前不属于选课阶段")
        if "您不在可选课名单中" in html:
            raise RuntimeError("您不在可选课名单中，不可选课")

        soup = BeautifulSoup(html, "html.parser")
        cfg = BodyConfig()

        def val(name: str) -> str:
            tag = soup.find("input", {"name": name})
            if not tag or not tag.get("value"):
                raise RuntimeError(f"选课配置 {name} 获取失败")
            return tag["value"]

        cfg.ccdm = val("ccdm")
        cfg.bh_id = val("bh_id")
        jg = soup.find("input", {"name": "jg_id_1"}) or soup.find("input", {"name": "jg_id"})
        if not jg or not jg.get("value"):
            raise RuntimeError("jg_id 获取失败")
        cfg.jg_id = jg["value"]
        cfg.xsbj = val("xsbj")
        cfg.xz = val("xz")
        cfg.mzm = val("mzm")
        cfg.xslbdm = val("xslbdm")
        cfg.xbm = val("xbm")
        cfg.zyfx_id = val("zyfx_id")
        cfg.xqh_id = val("xqh_id")

        pattern = re.compile(r"queryCourse\(this,'(\d+)'")
        pattern1 = re.compile(r"queryCourse\(this,'(?:[^']*)','(\w+)'")
        for a in soup.find_all("a", onclick=True):
            onclick = a.get("onclick", "")
            m, m1 = pattern.search(onclick), pattern1.search(onclick)
            if m and m1:
                cfg.xkkz_id[m.group(1)] = m1.group(1)
        if not cfg.xkkz_id:
            raise RuntimeError("XkkzID 获取失败")

        self.body_config = cfg
        return cfg

    def fetch_courses_online(self, cfg: dict[str, Any], jxbmc: str = "") -> dict[str, Any]:
        xn = cfg["time"]["XueNian"]
        xq = cfg["time"]["XueQi"]
        xqm = "3" if xq == "1" else "12" if xq == "2" else ""
        if not xqm:
            raise ValueError("学期格式错误")
        xnmc = f"{xn}-{int(xn) + 1}"
        data = {
            "xnmc": xnmc,
            "xqmc": xq,
            "xnm": xn,
            "xqm": xqm,
            "_search": "false",
            "nd": str(int(time.time())),
            "queryModel.showCount": "9999",
            "queryModel.currentPage": "1",
            "queryModel.sortOrder": "asc",
            "time": "0",
        }
        if jxbmc:
            data["jxbmc"] = jxbmc
        text = self.post_with_retry(
            "https://newjw.hdu.edu.cn/jwglxt/rwlscx/rwlscx_cxRwlsIndex.html?doType=query&gnmkdm=N1548",
            data,
            timeout=CATALOG_TIMEOUT,
        )
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        if "无功能权限" in text:
            raise RuntimeError("任务落实查询并未开放")
        return json.loads(text)

    def get_do_jxb_id(self, cfg: dict[str, Any], item: dict[str, Any], kklxdm: str) -> str:
        assert self.body_config
        bc = self.body_config
        xqm = "3" if cfg["time"]["XueQi"] == "1" else "12"
        nj = "20" + bc.bh_id[:2]
        form = {
            "bklx_id": "0",
            "njdm_id": nj,
            "xkxnm": cfg["time"]["XueNian"],
            "xkxqm": xqm,
            "kklxdm": kklxdm,
            "kch_id": item["kch_id"],
            "xkkz_id": bc.xkkz_id[kklxdm],
            "xsbj": bc.xsbj,
            "ccdm": bc.ccdm,
            "xz": bc.xz,
            "mzm": bc.mzm,
            "xslbdm": bc.xslbdm,
            "xbm": bc.xbm,
            "bh_id": bc.bh_id,
            "zyfx_id": bc.zyfx_id,
            "jg_id": bc.jg_id,
            "xqh_id": bc.xqh_id,
            "njdm_id_xs": self.njdm_id_xs,
            "zyh_id_xs": self.zyh_id_xs,
        }
        text = self.post(
            "https://newjw.hdu.edu.cn/jwglxt/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html?gnmkdm=N253512",
            form,
        )
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        rows = json.loads(text)
        for row in rows:
            if row.get("jxb_id") == item.get("jxb_id"):
                return row["do_jxb_id"]
        raise RuntimeError("未查询到 do_jxb_id")

    def select_course(
        self, cfg: dict[str, Any], do_jxb_id: str, kch_id: str, kklxdm: str, jxbzc: str
    ) -> dict[str, Any]:
        assert self.body_config
        bc = self.body_config
        form: dict[str, str] = {
            "jxb_ids": do_jxb_id,
            "kch_id": kch_id,
            "qz": "0",
            "njdm_id_xs": self.njdm_id_xs,
            "zyh_id_xs": self.zyh_id_xs,
            "xkkz_id": bc.xkkz_id[kklxdm],
        }
        if kklxdm == "01" and cfg.get("CrossGradeEnabled") == "1":
            form["njdm_id"] = "20" + jxbzc[:2]
            form["zyh_id"] = self.get_zyh_by_bh(jxbzc.split(";")[0])
        elif kklxdm == "01":
            form["njdm_id"] = self.njdm_id_xs
            form["zyh_id"] = self.zyh_id_xs
        text = self.post(
            "https://newjw.hdu.edu.cn/jwglxt/xsxk/zzxkyzbjk_xkBcZyZzxkYzb.html?gnmkdm=N253512",
            form,
        )
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        return json.loads(text)

    def cancel_course(self, cfg: dict[str, Any], do_jxb_id: str, kch_id: str) -> str:
        xqm = "3" if cfg["time"]["XueQi"] == "1" else "12"
        text = self.post(
            "https://newjw.hdu.edu.cn/jwglxt/xsxk/zzxkyzb_tuikBcZzxkYzb.html?gnmkdm=N253512",
            {
                "jxb_ids": do_jxb_id,
                "kch_id": kch_id,
                "xkxnm": cfg["time"]["XueNian"],
                "xkxqm": xqm,
            },
        )
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        return text

    def search_course_has_seat(self, cfg: dict[str, Any], kklxdm: str, jxbmc: str) -> bool:
        xqm = "3" if cfg["time"]["XueQi"] == "1" else "12"
        text = self.post(
            "https://newjw.hdu.edu.cn/jwglxt/xsxk/zzxkyzb_cxZzxkYzbPartDisplay.html?gnmkdm=N253512",
            {
                "xkxnm": cfg["time"]["XueNian"],
                "xkxqm": xqm,
                "kklxdm": kklxdm,
                "kspage": "1",
                "jspage": "10",
                "yl_list[0]": "1",
                "filter_list[0]": jxbmc,
                "njdm_id_xs": self.njdm_id_xs,
                "zyh_id_xs": self.zyh_id_xs,
            },
        )
        if "统一身份认证" in text:
            raise RuntimeError("可能登录过期")
        data = json.loads(text)
        return bool(data.get("tmpList"))

    def get_zyh_by_bh(self, bh: str) -> str:
        text = self.get(f"https://newjw.hdu.edu.cn/jwglxt/xtgl/comm_cxBjdmList.html?&bh={bh}")
        rows = json.loads(text)
        if not rows:
            raise RuntimeError("获取 zyh_id 失败")
        return rows[0]["zyh_id"]


KKLX_MAP = {
    "主修课程": "01",
    "通识选修课": "10",
    "体育分项": "05",
    "特殊课程": "09",
}
