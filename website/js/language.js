const translations = {
  pt: {
    navHome: "Início",
    navProjects: "Projetos",
    navRoadmap: "Roadmap",
    navAbout: "Sobre",
    navContact: "Contacto",

    heroEyebrow: "Laboratório digital independente",
    heroTitle: "PJCore Labs",
    heroSubtitle: "Software, IA, automação e ferramentas digitais criadas com propósito prático.",
    heroPrimary: "Ver projetos",
    heroSecondary: "Sobre o laboratório",

    aboutEyebrow: "Sobre",
    aboutTitle: "Uma casa para projetos digitais práticos.",
    aboutText: "A PJCore Labs é a marca central para projetos focados em produtividade, educação jurídica, automação, ferramentas de IA e sistemas pessoais de estação de trabalho.",

    projectsEyebrow: "Projetos",
    projectsTitle: "Projetos atuais e futuros",
    projectWorkstation: "Centro pessoal de controlo da estação de trabalho para monitorização, manutenção e produtividade.",
    projectSolicitadoria: "Repositório jurídico educativo criado com estrutura, disciplina e acesso público.",
    projectLeisUk: "Explicações claras sobre leis do Reino Unido para falantes de português, com fontes oficiais.",
    projectAiEncyclopedia: "Diretório de ferramentas de IA úteis, organizado para uso prático diário.",
    projectOrganizer: "Futuro sistema de organização pessoal para tarefas, notas, ideias e rotinas.",
    projectAiTools: "Pequenas ferramentas com IA pensadas para resolver problemas reais sem complexidade desnecessária.",

    valuesEyebrow: "Valores",
    valuesTitle: "Tecnologia simples, útil e honesta.",
    valuePracticalTitle: "Prática",
    valuePracticalText: "As ferramentas devem resolver problemas reais, não apenas parecer impressionantes.",
    valueTransparentTitle: "Transparente",
    valueTransparentText: "Os projetos devem ser compreensíveis, documentados e fáceis de verificar.",
    valueIndependentTitle: "Independente",
    valueIndependentText: "Construído passo a passo, sem depender de modas ou atalhos.",

    roadmapEyebrow: "Roadmap",
    roadmapTitle: "Próximos passos",
    roadmapOne: "Publicar a homepage oficial PJCore Labs v1.0.",
    roadmapTwo: "Ligar os projetos principais a páginas dedicadas.",
    roadmapThree: "Preparar os assets da marca, documentação e estrutura dos projetos.",
    roadmapFour: "Usar pjcorelabs.com como centro público dos futuros produtos digitais.",

    contactEyebrow: "Contacto",
    contactTitle: "Construir em silêncio. Publicar em condições.",
    contactText: "A PJCore Labs está em desenvolvimento ativo. Mais páginas de projetos e opções de contacto serão adicionadas em breve.",

    footerText: "Todos os direitos reservados."
  },

  en: {
    navHome: "Home",
    navProjects: "Projects",
    navRoadmap: "Roadmap",
    navAbout: "About",
    navContact: "Contact",

    heroEyebrow: "Independent digital lab",
    heroTitle: "PJCore Labs",
    heroSubtitle: "Software, AI, automation and digital tools built with practical purpose.",
    heroPrimary: "View projects",
    heroSecondary: "About the lab",

    aboutEyebrow: "About",
    aboutTitle: "A home for practical digital projects.",
    aboutText: "PJCore Labs is the central brand for projects focused on productivity, legal education, automation, AI tools and personal workstation systems.",

    projectsEyebrow: "Projects",
    projectsTitle: "Current and future projects",
    projectWorkstation: "Personal workstation control centre for monitoring, maintenance and productivity.",
    projectSolicitadoria: "Educational legal repository built with structure, discipline and public access.",
    projectLeisUk: "Clear explanations of UK law for Portuguese speakers, with official sources.",
    projectAiEncyclopedia: "Directory of useful AI tools, organised for practical daily use.",
    projectOrganizer: "Future personal organisation system for tasks, notes, ideas and routines.",
    projectAiTools: "Small AI-powered tools designed to solve real problems without unnecessary complexity.",

    valuesEyebrow: "Values",
    valuesTitle: "Simple, useful and honest technology.",
    valuePracticalTitle: "Practical",
    valuePracticalText: "Tools must solve real problems, not just look impressive.",
    valueTransparentTitle: "Transparent",
    valueTransparentText: "Projects should be understandable, documented and easy to verify.",
    valueIndependentTitle: "Independent",
    valueIndependentText: "Built step by step, without depending on hype or shortcuts.",

    roadmapEyebrow: "Roadmap",
    roadmapTitle: "Next steps",
    roadmapOne: "Publish the official PJCore Labs homepage v1.0.",
    roadmapTwo: "Connect the main projects with dedicated pages.",
    roadmapThree: "Prepare the brand assets, documentation and project structure.",
    roadmapFour: "Use pjcorelabs.com as the public centre for future digital products.",

    contactEyebrow: "Contact",
    contactTitle: "Building quietly. Publishing properly.",
    contactText: "PJCore Labs is under active development. More project pages and contact options will be added soon.",

    footerText: "All rights reserved."
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
