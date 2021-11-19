import './css/interface.css';
import './js/ol-styles.js';
import Trim from './Trim.svelte';
import './css/ol-overrides.css'

const app = new Trim({
	target: document.getElementById("trim-target"),
	props: JSON.parse(document.getElementById("trim-props").textContent),
});

export default app;
