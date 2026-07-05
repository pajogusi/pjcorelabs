const translations = {
  pt: {
    navHome: "Início",
    navProjects: "Projetos",
    navRoadmap: "Roadmap",
    navAbout: "Sobre",
    navContact: "Contacto",
    heroTitle: "PJCore Labs",
    heroSubtitle: "Software, IA, automação e ferramentas digitais.",
    heroStatus: "Site em construção."
  },
  en: {
    navHome: "Home",
    navProjects: "Projects",
    navRoadmap: "Roadmap",
    navAbout: "About",
    navContact: "Contact",
    heroTitle: "PJCore Labs",
    heroSubtitle: "Software, AI, automation and digital tools.",
    heroStatus: "Website under construction."
  }
};

function detectLanguage() {
  const saved = localStorage.getItem("pjcorelabs-language");
  if (saved) return saved;

  const browserLang = navigator.language || navigator.userLanguage || "en";

  if (browserLang.toLowerCase().startsWith("pt")) {
    return "pt";
  }

  return "en";
}

function setLanguage(lang) {
  localStorage.setItem("pjcorelabs-language", lang);
  document.documentElement.lang = lang;

  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.getAttribute("data-i18n");
    if (translations[lang] && translations[lang][key]) {
      element.textContent = translations[lang][key];
    }
  });

  document.querySelectorAll("[data-lang-button]").forEach((button) => {
    button.classList.toggle("active", button.dataset.langButton === lang);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const lang = detectLanguage();
  setLanguage(lang);

  document.querySelectorAll("[data-lang-button]").forEach((button) => {
    button.addEventListener("click", () => {
      setLanguage(button.dataset.langButton);
    });
  });
});
