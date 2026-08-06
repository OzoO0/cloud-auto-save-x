import logging
import os
import re
import time


logger = logging.getLogger(__name__)


class Auto_unarchive:
    default_config = {
        "tips_": "自动云解压(zip|rar|7z)到保存目录，在任务插件选项中启用，该功能需SVIP支持",
        "global_enable": False,  # 是否全局开启自动解压
        "max_concurrent": 3,  # 限制同时解压的任务数
    }

    default_task_config = {
        "enable": False,  # 是否自动解压
        "auto_clean": True,  # 是否自动删除原始文件
        "auto_clean_zipdir": True,  # 是否删除占位目录，适用于一次性运行的任务，无须防止重复转存的占位目录
    }

    is_active = True  # 默认全局激活，由任务配置中开启

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        if kwargs:
            for key, _ in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])

    def run(self, task, **kwargs):
        account = kwargs.get("account")
        tree = kwargs.get("tree")

        task_config = task.get("addition", {}).get(self.plugin_name, self.default_task_config)

        if not str(self.global_enable).lower() == "true":
            if not task_config.get("enable"):
                logger.info(
                    "🟨 [%s] 未启用 auto_unarchive（任务插件选项 enable=false，且 global_enable 未开启）",
                    task.get("taskname", ""),
                )
                return task

        # 任务配置中是否自动删除原始文件
        self.auto_clean = task_config.get("auto_clean", True)
        self.auto_clean_zipdir = task_config.get("auto_clean_zipdir", False)

        try:
            savepath = re.sub(r"/{2,}", "/", f"/{task['savepath']}")
            target_pdir_fid = account.savepath_fid.get(savepath)

            if not target_pdir_fid:
                logger.warning("🟨 [%s] 未找到保存目录 fid，跳过云解压：%s", task.get("taskname", ""), savepath)

            drive_type = getattr(account, "DRIVE_TYPE", "") or ("quark" if account.__class__.__name__ == "Quark" else "")
            if drive_type and drive_type not in {"quark", "uc"}:
                logger.warning("⚠️ [%s] %s 网盘未适配云解压，跳过插件执行", task["taskname"], drive_type)
                return task

            # 获取待解压节点列表
            all_zip_nodes = [
                node
                for node in tree.all_nodes()
                if node.data
                and not node.data.get("is_dir")
                and re.search(r"\.(zip|rar|7z)$", node.tag, re.I)
            ]
            if not all_zip_nodes:
                logger.info("🟨 [%s] 未发现压缩包（zip|rar|7z），跳过云解压", task.get("taskname", ""))
                return task

            wait_list = all_zip_nodes.copy()  # 等待提交队列
            active_tasks = []  # 正在解压队列
            all_move_fids = []
            all_cleanup_fids = []

            logger.info("📦 [%s] 共有 %s 个任务，控制并发数为: %s", task["taskname"], len(wait_list), self.max_concurrent)

            while wait_list or active_tasks:

                while len(active_tasks) < int(self.max_concurrent) and wait_list:
                    node = wait_list.pop(0)
                    zip_fid = node.data["fid"]
                    zip_name = node.data["file_name_re"]
                    main_name = os.path.splitext(zip_name)[0]

                    res = account.unarchive(zip_fid, target_pdir_fid)
                    if res.get("code") == 0:
                        task_id = res["data"]["task_id"]
                        active_tasks.append(
                            {
                                "task_id": task_id,
                                "zip_fid": zip_fid,
                                "main_name": main_name,
                                "zip_name": zip_name,
                            }
                        )
                        logger.info("  ▶️ 提交解压: %s", zip_name)
                    else:
                        logger.warning("  ❌ 提交失败: %s (%s)", zip_name, res.get("message"))
                        if "concurrent" in res.get("message", ""):
                            wait_list.insert(0, node)
                            break
                    time.sleep(1)

                for p_task in active_tasks[:]:
                    q_res = account.query_task(p_task["task_id"])

                    if q_res.get("code") == 0:
                        logger.info("  ✅ 解压完成: %s", p_task["zip_name"])
                        self._process_files(
                            account,
                            p_task,
                            q_res,
                            target_pdir_fid,
                            all_move_fids,
                            all_cleanup_fids,
                        )
                        active_tasks.remove(p_task)
                    elif q_res.get("code") == 1:
                        pass
                    else:
                        logger.warning("  ⚠️ 任务异常: %s %s", p_task["zip_name"], q_res.get("message", ""))
                        active_tasks.remove(p_task)

                if active_tasks:
                    time.sleep(5)

            if all_move_fids:
                logger.info("🚀 任务全部解压完成，开始批量移动 %s 个文件...", len(all_move_fids))
                if account.move_files(all_move_fids, target_pdir_fid).get("code") == 0:
                    if all_cleanup_fids and account.delete(all_cleanup_fids):
                        logger.info("🧹 批量清理完成")

        except Exception as e:
            logger.exception("❌ 运行异常: %s", e)
        return task

    def _process_files(self, account, p_task, q_res, target_fid, move_list, clean_list):
        """处理文件重命名逻辑"""
        # 获取解压出来压缩包同名目录的fid
        un_list = q_res.get("data", {}).get("unarchive_result", {}).get("list", [])
        sub_dir_fid = next(
            (i["fid"] for i in un_list if p_task["main_name"] == i["file_name"]), None
        )
        if not sub_dir_fid:
            return

        if self.auto_clean:
            # 压缩包加入清理队列
            clean_list.append(p_task["zip_fid"])
            if self.auto_clean_zipdir:
                # 解压目录加入清理队列
                clean_list.append(sub_dir_fid)
            else:
                # 重命名解压目录为压缩包名称，占位，避免下次重复转存
                account.rename(sub_dir_fid, p_task["zip_name"])
        else:
            # 不自动清理时，原压缩包占位，将解压目录加入清理队列
            clean_list.append(sub_dir_fid)

        # 获取解压目录下的所有文件
        ls_res = account.ls_dir(sub_dir_fid)
        items = ls_res.get("data", {}).get("list", [])
        for item in items:
            move_list.append(item["fid"])

        if len(items) == 1:
            item = items[0]
            # 重命名文件 /zip1/xx.mp4 -> /zip1/zip1.mp4
            # 当压缩包里只有一个文件时，执行按压缩包名称重命名
            ext = os.path.splitext(item["file_name"])[1]
            new_name = f"{p_task['main_name']}{ext}"
            account.rename(item["fid"], new_name)
            logger.info("    └─ 重命名: %s", new_name)
