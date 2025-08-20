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

/**
 * 顔画像に関する操作をまとめたコントローラクラス
 *
 * 主な機能:
 *  - 顔画像の一覧表示
 *  - 顔画像のアップロード
 *  - 顔画像の検索
 */
@Controller
@RequestMapping("/faces")  // このクラスの全メソッドは "/faces" 配下のURLで呼び出される
public class FaceImageController {

    private final FaceImageService faceImageService;

    /**
     * アップロード先ディレクトリのパス
     * application.properties から upload.dir プロパティの値を読み込む
     */
    @Value("${upload.dir}")
    private String uploadDir;

    /**
     * コンストラクタインジェクション
     * FaceImageService を注入し、DB操作を利用できるようにする
     */
    @Autowired
    public FaceImageController(FaceImageService faceImageService) {
        this.faceImageService = faceImageService;
    }

    /**
     * 顔画像一覧の表示処理
     * 
     * @param model 画面に渡すデータを格納するオブジェクト
     * @return faces/index テンプレートを返す
     */
    @GetMapping
    public String showFaceImages(Model model) {
        List<FaceImage> faceImages = faceImageService.findAll(); // DBから全件取得
        model.addAttribute("faceImages", faceImages);            // Viewにデータを渡す
        return "faces/index";                                   // faces/index.html を表示
    }

    /**
     * アップロードフォームの表示処理
     *
     * @param model Viewに渡すオブジェクト
     * @return faces/upload テンプレート
     */
    @GetMapping("/upload")
    public String showUploadForm(Model model) {
        model.addAttribute("faceForm", new FaceForm()); // 空のフォームオブジェクトを渡す
        return "faces/upload";
    }

    /**
     * 顔画像アップロード処理
     *
     * @param faceForm 入力フォームから受け取る情報（馬名や馬場状態）
     * @param file アップロードされた画像ファイル
     * @return アップロード後に顔画像一覧へリダイレクト
     * @throws IOException ファイル保存に失敗した場合
     */
    @PostMapping("/upload")
    public String uploadFaceImage(@ModelAttribute FaceForm faceForm,
                                  @RequestParam("file") MultipartFile file) throws IOException {

        // 元のファイル名から拡張子を取得
        String extension = StringUtils.getFilenameExtension(file.getOriginalFilename());

        // UUID を利用してファイル名をユニークにする（重複回避 & 日本語ファイル名による不具合防止）
        String uniqueFileName = UUID.randomUUID().toString() + "." + extension;

        // アップロード先のディレクトリが存在しない場合は作成
        File uploadPath = new File(uploadDir);
        if (!uploadPath.exists()) {
            uploadPath.mkdirs();
        }

        // 保存先ファイルを指定して保存処理を実行
        File destination = new File(uploadPath, uniqueFileName);
        file.transferTo(destination);

        // FaceImage エンティティを作成してDBに保存
        FaceImage faceImage = new FaceImage(
            faceForm.getHorseName(),       // 馬名
            faceForm.getTrackCondition(),  // 馬場状態
            "/uploads/" + uniqueFileName   // 公開用の相対パス（静的リソース設定で公開される）
        );
        faceImage.setScore(0); // DBのNOT NULL制約を回避するため、スコア初期値を設定

        faceImageService.save(faceImage); // DBへ保存

        // 一覧ページへリダイレクト（F5での再送信防止にもなる）
        return "redirect:/faces";
    }

    /**
     * 顔画像の検索処理
     *
     * @param horseName 馬名での検索条件（任意）
     * @param trackCondition 馬場状態での検索条件（任意）
     * @param model 検索結果を格納するオブジェクト
     * @return faces/index テンプレートに検索結果を表示
     */
    @GetMapping("/search")
    public String search(@RequestParam(required = false) String horseName,
                         @RequestParam(required = false) String trackCondition,
                         Model model) {

        List<FaceImage> results;

        // 入力条件に応じて検索メソッドを分岐
        if (horseName != null && trackCondition != null) {
            results = faceImageService.findByHorseNameAndTrackCondition(horseName, trackCondition);
        } else if (horseName != null) {
            results = faceImageService.findByHorseName(horseName);
        } else if (trackCondition != null) {
            results = faceImageService.findByTrackCondition(trackCondition);
        } else {
            results = faceImageService.findAll(); // 条件なし → 全件表示
        }

        // 検索結果をViewへ渡す
        model.addAttribute("faceImages", results);
        return "faces/index";
    }
}
