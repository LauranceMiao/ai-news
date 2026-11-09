-- 修复旧库遗留：favorite / history 的外键指向历史遗留的 user 表，
-- 而 ORM 实际使用 t_user。这里把外键重指到 t_user，再删除废弃的 user 表。
SET NAMES utf8mb4;

ALTER TABLE `favorite` DROP FOREIGN KEY `fk_favorite_user`;
ALTER TABLE `favorite`
  ADD CONSTRAINT `fk_favorite_user` FOREIGN KEY (`user_id`) REFERENCES `t_user` (`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `history` DROP FOREIGN KEY `fk_history_user`;
ALTER TABLE `history`
  ADD CONSTRAINT `fk_history_user` FOREIGN KEY (`user_id`) REFERENCES `t_user` (`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;

DROP TABLE IF EXISTS `user`;
