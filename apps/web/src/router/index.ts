import { createRouter, createWebHistory } from "vue-router";
import WorkBench from "../views/WorkBench.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      name: "workbench",
      component: WorkBench,
    },
  ],
});

export default router;
