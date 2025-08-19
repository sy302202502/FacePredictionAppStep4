package com.faceprediction.controller;

import java.io.File;
import java.io.IOException;
import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
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

    @Autowired
    public FaceImageController(FaceImageService faceImageService) {
        this.faceImageService = faceImageService;
    }

    @GetMapping
    public String showFaceImages(Model model) {
        List<FaceImage> faceImages = faceImageService.findAll();
        model.addAttribute("faceImages", faceImages);
        return "faces/index";
    }

    @GetMapping("/upload")  
    public String showUploadForm(Model model) {
        model.addAttribute("faceForm", new FaceForm());
        return "faces/upload";
    }


    @PostMapping("/upload")
    public String uploadFaceImage(@ModelAttribute FaceImage faceImage,
                                   @RequestParam("file") MultipartFile file) throws IOException {
        String fileName = StringUtils.cleanPath(file.getOriginalFilename());
        String uploadDir = "src/main/resources/static/uploads/";
        File uploadPath = new File(uploadDir);
        if (!uploadPath.exists()) {
            uploadPath.mkdirs();
        }

        File destination = new File(uploadDir + fileName);
        file.transferTo(destination);

        faceImage.setImagePath("/uploads/" + fileName);
        faceImageService.save(faceImage);

        return "redirect:/faces";
    }

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