export const AI_CATEGORY_OPTIONS = [
    {
        value: "portrait",
        label: "Portrait",
        description: "A person or close-up where facial identity and expression matter.",
        preserveSuggestions: ["Face shape", "Eyes", "Expression", "Hair silhouette", "Clothing outline"],
        simplifySuggestions: ["Skin texture", "Individual hair strands", "Background clutter", "Fabric texture", "Soft shadows"],
    },
    {
        value: "pet",
        label: "Pet",
        description: "An animal where its silhouette and distinctive features or markings matter.",
        preserveSuggestions: ["Eyes", "Nose and mouth", "Ears", "Coat markings", "Body silhouette"],
        simplifySuggestions: ["Fur strands", "Grass and foliage", "Background clutter", "Mottled shading", "Small highlights"],
    },
    {
        value: "landscape",
        label: "Landscape",
        description: "Scenery dominated by sky, land, water, trees, or a horizon.",
        preserveSuggestions: ["Horizon", "Major landforms", "Water edges", "Main tree shapes", "Focal building"],
        simplifySuggestions: ["Individual leaves", "Grass blades", "Cloud texture", "Water reflections", "Distant details"],
    },
    {
        value: "architecture",
        label: "Architecture",
        description: "A building or structure where geometry, perspective, windows, and doors matter.",
        preserveSuggestions: ["Roofline", "Windows and doors", "Perspective", "Building silhouette", "Major facade shapes"],
        simplifySuggestions: ["Brick or stone texture", "Window reflections", "Small railings", "Background people and cars", "Tiny facade details"],
    },
    {
        value: "still_life",
        label: "Still life",
        description: "A composed group of objects such as flowers, food, or household items.",
        preserveSuggestions: ["Object silhouettes", "Object overlaps", "Main colour blocks", "Distinctive shapes", "Important highlights"],
        simplifySuggestions: ["Fabric texture", "Reflections", "Label text", "Shadow gradients", "Small decorations"],
    },
    {
        value: "illustration",
        label: "Illustration / other",
        description: "A drawing, painting, or mixed subject that does not fit another category.",
        preserveSuggestions: ["Character silhouette", "Pose", "Facial expression", "Major colour blocks", "Important props"],
        simplifySuggestions: ["Tiny decorations", "Repeated patterns", "Brush texture", "Shading gradients", "Background details"],
    },
] as const;

export type AICategory = (typeof AI_CATEGORY_OPTIONS)[number]["value"];

export const DEFAULT_AI_CATEGORY: AICategory = "illustration";

export function getAICategoryOption(category: AICategory) {
    return AI_CATEGORY_OPTIONS.find((option) => option.value === category)
        ?? AI_CATEGORY_OPTIONS.find((option) => option.value === DEFAULT_AI_CATEGORY)!;
}

export function normalizeAICategory(value: unknown): AICategory {
    if (typeof value !== "string") return DEFAULT_AI_CATEGORY;

    const normalized = value.trim().toLowerCase().replace(/[\s-]+/g, "_");
    const option = AI_CATEGORY_OPTIONS.find((candidate) => candidate.value === normalized);
    return option?.value ?? DEFAULT_AI_CATEGORY;
}
