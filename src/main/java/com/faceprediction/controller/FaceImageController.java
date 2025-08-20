package com.faceprediction.controller;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;

import com.faceprediction.entity.FaceImage;
import com.faceprediction.form.FaceForm;
import com.faceprediction.service.FaceImageService;

@Controller
@RequestMapping("/faces")
public class FaceImageController {

    private final FaceImageService faceImageService;

    @Value("${upload.dir}")
    private String uploadDir;  // application.properties から取得

    @Autowired
    public FaceImageController(FaceImageService faceImageService) {
        this.faceImageService = faceImageService;
    }

    // 顔画像一覧表示
    @GetMapping
    public String showFaceImages(Model model) {
        List<FaceImage> faceImages = faceImageService.findAll();
        model.addAttribute("faceImages", faceImages);
        return "faces/index";
    }

    // アップロードフォーム表示
    @GetMapping("/upload")
    public String showUploadForm(Model model) {
        model.addAttribute("faceForm", new FaceForm());
        return "faces/upload";
    }

    // 顔画像アップロード処理
    @PostMapping("/upload")
    public String uploadFaceImage(@ModelAttribute FaceForm faceForm,
                                  @RequestParam("file") MultipartFile file) throws IOException {

        // ファイル名を UUID でユニークにして、日本語ファイル名などによる不具合を回避
        String extension = StringUtils.getFilenameExtension(file.getOriginalFilename());
        String uniqueFileName = UUID.randomUUID().toString() + "." + extension;

        // アップロード先ディレクトリ作成（存在しない場合）
        File uploadPath = new File(uploadDir);
        if (!uploadPath.exists()) {
            uploadPath.mkdirs();
        }

        // ファイル保存
        File destination = new File(uploadPath, uniqueFileName);
        file.transferTo(destination);

        // エンティティ作成と保存
        FaceImage faceImage = new FaceImage(
            faceForm.getHorseName(),
            faceForm.getTrackCondition(),
            "/uploads/" + uniqueFileName  // 表示用の相対パス
        );
        faceImage.setScore(0); // NULL制約回避のため初期値を設定

        faceImageService.save(faceImage);

        return "redirect:/faces";
    }

    // 検索処理
    @GetMapping("/search")
    public String search(@RequestParam(required = false) String horseName,
                         @RequestParam(required = false) String trackCondition,
                         Model model) {
        List<FaceImage> results;
        if (horseName != null && trackCondition != null) {
            results = faceImageService.findByHorseNameAndTrackCondition(horseName, trackCondition);
        } else if (horseName != null) {
            results = faceImageService.findByHorseName(horseName);
        } else if (trackCondition != null) {
            results = faceImageService.findByTrackCondition(trackCondition);
        } else {
            results = faceImageService.findAll();
        }

        model.addAttribute("faceImages", results);
        return "faces/index";
    }
}