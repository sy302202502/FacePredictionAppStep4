package com.faceprediction.controller;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * 馬の写真（uploads）の一覧。VPS の外へのバックアップ用（tools/backup_pull.py が読み、増えた分だけを取りに来る）。
 * 写真そのものは /uploads/** で公開済みなので、一覧にも秘密は無い。管理用のパドック写真（paddock）は載せない。
 * 1行 = 「バイト数 TAB 相対パス」
 */
@Controller
public class UploadsIndexController {

    /** 一覧に載せるフォルダ（公開している馬の写真だけ） */
    private static final List<String> DIRS = List.of("candidates", "race_specific", "horses");

    @Value("${upload.dir:#{systemProperties['user.home']}/faceapp/uploads}")
    private String uploadDir;

    @GetMapping(value = "/uploads/_index.txt", produces = MediaType.TEXT_PLAIN_VALUE + ";charset=UTF-8")
    @ResponseBody
    public ResponseEntity<String> index() {
        Path root = Paths.get(uploadDir);
        StringBuilder sb = new StringBuilder();
        for (String dir : DIRS) {
            Path base = root.resolve(dir);
            if (!Files.isDirectory(base)) continue;
            try (Stream<Path> walk = Files.walk(base, 3)) {
                for (Path p : walk.filter(Files::isRegularFile).sorted().collect(Collectors.toList())) {
                    String rel = root.relativize(p).toString().replace('\\', '/');
                    if (rel.contains("\t") || rel.contains("\n")) continue;
                    sb.append(Files.size(p)).append('\t').append(rel).append('\n');
                }
            } catch (IOException e) {
                return ResponseEntity.internalServerError().body("index failed: " + dir + "\n");
            }
        }
        return ResponseEntity.ok(sb.toString());
    }
}
