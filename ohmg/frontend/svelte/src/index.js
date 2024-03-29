import Index from '@src/lib/pages/Index.svelte';

const app = new Index({
	target: document.getElementById("index-target"),
	props: JSON.parse(document.getElementById("index-props").textContent),
});

export default app;