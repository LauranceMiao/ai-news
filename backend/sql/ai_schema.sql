-- AI 新闻聚合与问答系统：在 news_app 克隆库基础上新增 AI 相关表
SET NAMES utf8mb4;

-- 清理旧库遗留（ORM 使用 t_user；ai_chat 被 ai_session/ai_message 取代）
DROP TABLE IF EXISTS `ai_chat`;
DROP TABLE IF EXISTS `user`;

CREATE TABLE IF NOT EXISTS `news_chunk` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '切片ID',
  `news_id` INT UNSIGNED NOT NULL COMMENT '新闻ID',
  `chunk_index` INT NOT NULL DEFAULT 0 COMMENT '切片序号',
  `content` TEXT NOT NULL COMMENT '切片文本',
  `char_start` INT NOT NULL DEFAULT 0 COMMENT '原文起始字符',
  `char_end` INT NOT NULL DEFAULT 0 COMMENT '原文结束字符',
  `token_count` INT NOT NULL DEFAULT 0 COMMENT '估算token',
  `embedding` MEDIUMBLOB NULL COMMENT 'float32 向量',
  `dim` INT NOT NULL DEFAULT 0 COMMENT '向量维度',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_news_chunk` (`news_id`, `chunk_index`),
  CONSTRAINT `fk_chunk_news` FOREIGN KEY (`news_id`) REFERENCES `news` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='新闻切片与向量';

CREATE TABLE IF NOT EXISTS `ai_summary` (
  `news_id` INT UNSIGNED NOT NULL COMMENT '新闻ID',
  `summary` TEXT NOT NULL COMMENT '摘要',
  `points` JSON NULL COMMENT '要点列表',
  `model` VARCHAR(50) NULL COMMENT '生成模型',
  `prompt_tokens` INT NOT NULL DEFAULT 0,
  `completion_tokens` INT NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`news_id`),
  CONSTRAINT `fk_summary_news` FOREIGN KEY (`news_id`) REFERENCES `news` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='新闻AI摘要缓存';

CREATE TABLE IF NOT EXISTS `ai_digest` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `digest_date` DATE NOT NULL COMMENT '日期',
  `category_id` INT UNSIGNED NULL COMMENT '分类，NULL表示全站',
  `content` TEXT NOT NULL COMMENT '今日要闻正文',
  `refs` JSON NULL COMMENT '引用的新闻',
  `model` VARCHAR(50) NULL,
  `prompt_tokens` INT NOT NULL DEFAULT 0,
  `completion_tokens` INT NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_digest` (`digest_date`, `category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='今日要闻缓存';

CREATE TABLE IF NOT EXISTS `ai_session` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` INT UNSIGNED NULL COMMENT '匿名会话为空',
  `title` VARCHAR(100) NULL COMMENT '会话标题',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_session_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI会话';

CREATE TABLE IF NOT EXISTS `ai_message` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `session_id` INT UNSIGNED NOT NULL,
  `role` ENUM('user','assistant') NOT NULL,
  `content` MEDIUMTEXT NOT NULL,
  `reasoning` MEDIUMTEXT NULL COMMENT '推理过程',
  `refs` JSON NULL COMMENT '引用新闻',
  `prompt_tokens` INT NOT NULL DEFAULT 0,
  `completion_tokens` INT NOT NULL DEFAULT 0,
  `latency_ms` INT NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_message_session` (`session_id`),
  CONSTRAINT `fk_message_session` FOREIGN KEY (`session_id`) REFERENCES `ai_session` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI消息';

